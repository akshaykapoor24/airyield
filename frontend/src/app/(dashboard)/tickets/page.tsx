"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Upload,
  Search,
  RefreshCw,
  FileSpreadsheet,
  Calculator,
  CheckCircle2,
  PlayCircle,
  Pencil,
  Trash2,
  X,
  Save,
  AlertTriangle,
  FileSearch,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import api from "@/lib/api";

type UploadedTicket = {
  id: number;
  batch_id: string;
  file_name: string;
  ticket_number: string | null;
  booking_ref: string | null;
  segment_type: string | null;
  invoice_type: string | null;
  invoice_no: string | null;
  ticket_date: string | null;
  last_name: string | null;
  first_name: string | null;
  sector: string | null;
  booking_class: string | null;
  departure_datetime: string | null;
  gds_pnr: string | null;
  airlines_code: string | null;
  airline_name: string | null;
  sell_fare: number | null;
  sell_tax: number | null;
  sell_tax_yq: number | null;
  sale_yr: number | null;
  sale_k3: number | null;
  rei_sell: number | null;
  seat_selection: number | null;
  excess_baggage: number | null;
  meals: number | null;
  rfd_sell: number | null;
  can_charge: number | null;
  booking_fee_sell: number | null;
  cgst_sell: number | null;
  sgst_sell: number | null;
  igst_sell: number | null;
  comm_sell: number | null;
  adm: number | null;
  incentive_sell: number | null;
  dis_sell: number | null;
  tds_sell: number | null;
  total_amt: number | null;
  paid_by_credit_card: number | null;
  net_amt: number | null;
  cc: string | null;
  acc_code: string | null;
  sold_to: string | null;
  customer_name: string | null;
  matched_deal_id: number | null;
  matched_deal_type: string | null;
  matched_deal_name: string | null;
  calculated_incentive: number | null;
  created_at: string;
  created_by_id: number;
};

type RunCalcResult = {
  ticket_id: number;
  matched: boolean;
  matched_deal_id: number | null;
  matched_deal_type: string | null;
  matched_deal_name: string | null;
  calculated_incentive: number | null;
  message: string;
};

type BatchRunCalcResult = {
  processed: number;
  matched: number;
  unmatched: number;
  errors: number;
};

type DealMatchSummary = {
  deal_id: number;
  deal_type: string;
  deal_name: string;
  deal_no: string;
  calculated_incentive: number | null;
  valid_from: string | null;
  valid_to: string | null;
  deal_maker_name: string | null;
  is_best: boolean;
};

type MatchStep = {
  step: string;
  passed: boolean;
  ticket_value: string;
  deal_value: string;
  detail: string;
};

type IncentiveBreakdown = {
  targetCalcCols: string;
  sell_fare: number | null;
  sell_tax_yq_added: boolean;
  sell_tax_yq_value: number | null;
  sale_yr_added: boolean;
  sale_yr_value: number | null;
  base_total: number | null;
  incentiveAmtPct: string | number | null;
  formula: string;
  result: number | null;
};

type PLBDiagnostic = {
  plb_key: string;
  raw_plb: Record<string, unknown>;
  steps: MatchStep[];
  incentive_breakdown: IncentiveBreakdown | null;
  plb_overall_match: boolean;
};

type DealDiagnosticItem = {
  deal_id: number;
  deal_type: string;
  deal_name: string;
  deal_no: string;
  valid_from: string | null;
  valid_to: string | null;
  trigger_type: string | null;
  deal_validity_step: MatchStep;
  plbs: PLBDiagnostic[];
  overall_match: boolean;
  best_incentive: number | null;
};

type MatchDiagnosis = {
  ticket_id: number;
  raw_airline_code: string;
  normalized_codes: string[];
  airline_resolved: string | null;
  airline_resolution_detail: string;
  raw_departure: string | null;
  raw_ticket_date: string | null;
  travel_date: string | null;
  travel_date_detail: string;
  segment_type: string | null;
  booking_class: string | null;
  cabin_groups_resolved: string[];
  cabin_resolution_detail: string;
  invoice_type: string | null;
  sell_fare: number | null;
  sell_tax_yq: number | null;
  sale_yr: number | null;
  total_deals_checked: number;
  matched_count: number;
  deals: DealDiagnosticItem[];
};

function dealNo(type: string | null, id: number | null): string | null {
  if (!type || !id) return null;
  const prefix = type === "airline" ? "AIR" : type === "b2b" ? "B2B" : "UPL";
  return `${prefix}-${String(id).padStart(4, "0")}`;
}

function fmt(v: number | null | undefined) {
  if (v == null) return "—";
  return v.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function txt(v: string | null | undefined) {
  return v ?? <span className="text-gray-300">—</span>;
}

const PAGE_SIZE = 20;

const TEXT_HEADERS: Array<{ label: string; key: keyof UploadedTicket }> = [
  { label: "Ticket #", key: "ticket_number" },
  { label: "Booking Ref", key: "booking_ref" },
  { label: "Segment Type", key: "segment_type" },
  { label: "Invoice Type", key: "invoice_type" },
  { label: "Invoice No", key: "invoice_no" },
  { label: "Ticket Date", key: "ticket_date" },
  { label: "Last Name", key: "last_name" },
  { label: "First Name", key: "first_name" },
  { label: "Sector", key: "sector" },
  { label: "Class", key: "booking_class" },
  { label: "Departure", key: "departure_datetime" },
  { label: "GDS PNR", key: "gds_pnr" },
  { label: "Airline Code", key: "airlines_code" },
  { label: "Airline Name", key: "airline_name" },
];

const NUM_HEADERS: Array<{ label: string; key: keyof UploadedTicket }> = [
  { label: "Sell Fare", key: "sell_fare" },
  { label: "Sell Tax", key: "sell_tax" },
  { label: "Sell Tax YQ", key: "sell_tax_yq" },
  { label: "Sale YR", key: "sale_yr" },
  { label: "Sale K3", key: "sale_k3" },
  { label: "REI Sell", key: "rei_sell" },
  { label: "Seat Sel.", key: "seat_selection" },
  { label: "Exc. Baggage", key: "excess_baggage" },
  { label: "Meals", key: "meals" },
  { label: "RFD Sell", key: "rfd_sell" },
  { label: "CAN Charge", key: "can_charge" },
  { label: "Booking Fee", key: "booking_fee_sell" },
  { label: "CGST Sell", key: "cgst_sell" },
  { label: "SGST Sell", key: "sgst_sell" },
  { label: "IGST Sell", key: "igst_sell" },
  { label: "Comm Sell", key: "comm_sell" },
  { label: "ADM", key: "adm" },
  { label: "Incentive Sell", key: "incentive_sell" },
  { label: "DIS Sell", key: "dis_sell" },
  { label: "TDS Sell", key: "tds_sell" },
  { label: "Total Amt", key: "total_amt" },
  { label: "Paid By CC", key: "paid_by_credit_card" },
  { label: "Net AMT", key: "net_amt" },
];

// ── Diagnosis Modal ────────────────────────────────────────────────────────

function StepRow({ step }: { step: MatchStep }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`rounded-lg border px-3 py-2 text-[11px] ${step.passed ? "border-green-100 bg-green-50/30" : "border-red-100 bg-red-50/30"}`}>
      <div className="flex items-center gap-2 cursor-pointer" onClick={() => setOpen((o) => !o)}>
        <span className={`text-[13px] font-bold ${step.passed ? "text-green-600" : "text-red-500"}`}>
          {step.passed ? "✓" : "✗"}
        </span>
        <span className="font-semibold text-gray-700 w-32 shrink-0">{step.step}</span>
        <span className="px-1.5 py-0.5 rounded bg-blue-50 border border-blue-100 text-blue-700 font-mono text-[10px] truncate max-w-[140px]" title={step.ticket_value}>
          {step.ticket_value}
        </span>
        <span className="text-gray-300 text-[10px]">→</span>
        <span className="px-1.5 py-0.5 rounded bg-gray-100 border border-gray-200 text-gray-600 font-mono text-[10px] truncate max-w-[140px]" title={step.deal_value}>
          {step.deal_value}
        </span>
        <button className="ml-auto text-gray-400 hover:text-gray-600">
          {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </button>
      </div>
      {open && (
        <p className="mt-1.5 pl-5 text-[10px] text-gray-500 italic leading-relaxed">{step.detail}</p>
      )}
    </div>
  );
}

function PLBBlock({ plb }: { plb: PLBDiagnostic }) {
  const [rawOpen, setRawOpen] = useState(false);
  const bk = plb.incentive_breakdown;
  return (
    <div className={`rounded-xl border p-3 mt-2 ${plb.plb_overall_match ? "border-green-300 bg-green-50/20" : "border-gray-200 bg-white"}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${plb.plb_overall_match ? "bg-green-600 text-white" : "bg-gray-200 text-gray-500"}`}>
          {plb.plb_key}
        </span>
        <span className={`text-[10px] font-semibold ${plb.plb_overall_match ? "text-green-700" : "text-gray-400"}`}>
          {plb.plb_overall_match ? "All filters passed" : "One or more filters failed"}
        </span>
        <button
          onClick={() => setRawOpen((o) => !o)}
          className="ml-auto text-[9px] text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-1.5 py-0.5"
        >
          {rawOpen ? "Hide raw PLB" : "View raw PLB JSON"}
        </button>
      </div>

      {rawOpen && (
        <pre className="text-[9px] bg-gray-900 text-green-300 rounded-lg p-2.5 overflow-x-auto mb-2 leading-relaxed">
          {JSON.stringify(plb.raw_plb, null, 2)}
        </pre>
      )}

      <div className="space-y-1.5">
        {plb.steps.map((s, i) => <StepRow key={i} step={s} />)}
      </div>

      {/* Incentive breakdown — always shown */}
      {bk && (
        <div className={`mt-3 rounded-lg border px-3 py-2 text-[10px] ${plb.plb_overall_match ? "border-amber-200 bg-amber-50/40" : "border-gray-100 bg-gray-50/50"}`}>
          <p className="font-bold text-gray-600 mb-1.5 uppercase tracking-wide text-[9px]">
            Incentive Calculation {!plb.plb_overall_match && <span className="text-gray-400 font-normal">(hypothetical — filters did not pass)</span>}
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-gray-500">
            <span>targetCalcCols</span><span className="font-mono text-gray-800">{String(bk.targetCalcCols ?? "—")}</span>
            <span>sell_fare</span><span className="font-mono text-gray-800">₹ {bk.sell_fare ?? "—"}</span>
            {bk.sell_tax_yq_added && <><span>+ sell_tax_yq</span><span className="font-mono text-gray-800">₹ {bk.sell_tax_yq_value ?? 0}</span></>}
            {bk.sale_yr_added && <><span>+ sale_yr</span><span className="font-mono text-gray-800">₹ {bk.sale_yr_value ?? 0}</span></>}
            <span className="font-semibold text-gray-700">base total</span><span className="font-mono font-semibold text-gray-800">₹ {bk.base_total ?? "—"}</span>
            <span>incentiveAmtPct</span><span className="font-mono text-gray-800">{bk.incentiveAmtPct ?? "—"}%</span>
          </div>
          <p className={`mt-1.5 font-mono font-bold text-sm ${plb.plb_overall_match ? "text-amber-700" : "text-gray-400"}`}>
            {String(bk.formula ?? "—")}
          </p>
        </div>
      )}
    </div>
  );
}

function DiagnosisModal({
  ticket,
  diagnosis,
  onClose,
}: {
  ticket: UploadedTicket;
  diagnosis: MatchDiagnosis;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100 bg-violet-50/40">
          <div>
            <div className="flex items-center gap-2">
              <FileSearch className="w-4 h-4 text-violet-600" />
              <h2 className="text-sm font-bold text-gray-900">Match Diagnosis</h2>
            </div>
            <p className="text-[11px] text-gray-500 mt-0.5">
              Ticket {ticket.ticket_number ?? ticket.booking_ref} ·{" "}
              <span className="font-semibold text-gray-700">{diagnosis.total_deals_checked}</span> deals checked ·{" "}
              <span className={`font-semibold ${diagnosis.matched_count > 0 ? "text-green-700" : "text-red-500"}`}>
                {diagnosis.matched_count} matched
              </span>
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-lg leading-none">×</button>
        </div>

        {/* scrollable body */}
        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">

          {/* ── Ticket trace ── */}
          <div className="rounded-xl border border-gray-200 p-3.5 bg-gray-50/50">
            <p className="text-[9px] font-bold uppercase tracking-wide text-violet-600 mb-2">Ticket Trace</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px]">
              <TraceRow label="Airline Code (raw)" value={diagnosis.raw_airline_code || "—"} />
              <TraceRow label="Normalized codes" value={diagnosis.normalized_codes.join(", ") || "—"} />
              <TraceRow
                label="Airline resolved"
                value={diagnosis.airline_resolved ?? "NOT FOUND"}
                ok={!!diagnosis.airline_resolved}
              />
            </div>
            <p className="text-[10px] text-gray-400 italic mt-1">{diagnosis.airline_resolution_detail}</p>

            <div className="border-t border-gray-100 my-2" />

            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px]">
              <TraceRow label="Raw departure" value={diagnosis.raw_departure ?? "—"} />
              <TraceRow label="Raw ticket date" value={diagnosis.raw_ticket_date ?? "—"} />
              <TraceRow
                label="Travel date (parsed)"
                value={diagnosis.travel_date ?? "PARSE FAILED"}
                ok={!!diagnosis.travel_date}
              />
            </div>
            <p className="text-[10px] text-gray-400 italic mt-1">{diagnosis.travel_date_detail}</p>

            <div className="border-t border-gray-100 my-2" />

            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px]">
              <TraceRow label="Segment Type" value={diagnosis.segment_type ?? "—"} />
              <TraceRow label="Invoice Type" value={diagnosis.invoice_type ?? "—"} />
              <TraceRow label="Booking Class" value={diagnosis.booking_class ?? "—"} />
              <TraceRow label="Cabin groups resolved" value={diagnosis.cabin_groups_resolved.join(", ") || "—"} />
              <TraceRow label="Sell Fare" value={diagnosis.sell_fare != null ? `₹ ${diagnosis.sell_fare}` : "—"} />
              <TraceRow label="Sell Tax YQ" value={diagnosis.sell_tax_yq != null ? `₹ ${diagnosis.sell_tax_yq}` : "—"} />
              <TraceRow label="Sale YR" value={diagnosis.sale_yr != null ? `₹ ${diagnosis.sale_yr}` : "—"} />
            </div>
            <p className="text-[10px] text-gray-400 italic mt-1">{diagnosis.cabin_resolution_detail}</p>
          </div>

          {/* ── Deal list ── */}
          {diagnosis.deals.length === 0 ? (
            <div className="py-8 text-center text-xs text-gray-400">
              {diagnosis.airline_resolved
                ? "No approved deals found for this airline. Add or approve a deal first."
                : "Airline code could not be resolved — no deals to diagnose."}
            </div>
          ) : (
            diagnosis.deals.map((d) => (
              <div
                key={`${d.deal_type}-${d.deal_id}`}
                className={`rounded-xl border p-4 ${d.overall_match ? "border-green-300 bg-green-50/30" : "border-gray-200 bg-white"}`}
              >
                {/* deal header */}
                <div className="flex items-center flex-wrap gap-2 mb-3">
                  {d.overall_match && (
                    <span className="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase bg-green-600 text-white">Matched</span>
                  )}
                  <span className="font-mono text-[10px] font-bold text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200">{d.deal_no}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border ${d.deal_type === "b2b" ? "bg-violet-50 text-violet-600 border-violet-200" : "bg-sky-50 text-sky-600 border-sky-200"}`}>
                    {d.deal_type}
                  </span>
                  <span className="text-[11px] font-semibold text-gray-800">{d.deal_name}</span>
                  {d.valid_from && d.valid_to && (
                    <span className="text-[10px] text-gray-400 ml-auto">
                      {d.valid_from.slice(0, 10)} → {d.valid_to.slice(0, 10)}
                    </span>
                  )}
                  {d.trigger_type && (
                    <span className="text-[10px] text-gray-500">trigger: <span className="font-semibold">{d.trigger_type}</span></span>
                  )}
                </div>

                {/* deal validity step */}
                <StepRow step={d.deal_validity_step} />

                {/* PLB entries */}
                {d.plbs.map((plb, i) => <PLBBlock key={i} plb={plb} />)}

                {d.overall_match && d.best_incentive != null && (
                  <p className="mt-3 text-xs font-bold text-green-700">
                    Best matched incentive: ₹ {d.best_incentive.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </p>
                )}
              </div>
            ))
          )}
        </div>

        {/* footer */}
        <div className="px-5 py-3 border-t border-gray-100 flex justify-end">
          <button onClick={onClose} className="px-4 py-1.5 rounded-lg bg-gray-100 text-gray-700 text-xs font-semibold hover:bg-gray-200">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function TraceRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <>
      <span className="text-gray-400">{label}</span>
      <span className={`font-mono font-semibold ${ok === false ? "text-red-500" : ok === true ? "text-green-700" : "text-gray-800"}`}>
        {value}
      </span>
    </>
  );
}

export default function TicketsPage() {
  const [tickets, setTickets] = useState<UploadedTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [calcLoading, setCalcLoading] = useState<Record<number, boolean>>({});
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchResult, setBatchResult] = useState<BatchRunCalcResult | null>(
    null,
  );
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [dealsModal, setDealsModal] = useState<{
    ticket: UploadedTicket;
    deals: DealMatchSummary[];
  } | null>(null);
  const [dealsLoading, setDealsLoading] = useState(false);

  // ── Diagnosis state ──────────────────────────────────────────────────────
  const [diagModal, setDiagModal] = useState<{ ticket: UploadedTicket; diagnosis: MatchDiagnosis } | null>(null);
  const [diagLoading, setDiagLoading] = useState<Record<number, boolean>>({});

  // ── Edit / Delete state ──────────────────────────────────────────────────
  const [editModal,       setEditModal]       = useState<UploadedTicket | null>(null);
  const [editForm,        setEditForm]        = useState<Partial<UploadedTicket>>({});
  const [editSaving,      setEditSaving]      = useState(false);
  const [editError,       setEditError]       = useState("");
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [deleteLoading,   setDeleteLoading]   = useState(false);

  const fetchTickets = useCallback(async () => {
    setLoading(true);
    setApiError("");
    try {
      const { data } = await api.get<UploadedTicket[]>("/tickets/uploads");
      setTickets(data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response
        ?.data?.detail;
      setApiError(msg ?? "Failed to load tickets.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTickets();
  }, [fetchTickets]);

  const filtered = tickets.filter((t) => {
    const q = search.toLowerCase();
    return (
      !q ||
      (t.ticket_number ?? "").toLowerCase().includes(q) ||
      (t.gds_pnr ?? "").toLowerCase().includes(q) ||
      (t.last_name ?? "").toLowerCase().includes(q) ||
      (t.first_name ?? "").toLowerCase().includes(q) ||
      (t.airlines_code ?? "").toLowerCase().includes(q) ||
      (t.airline_name ?? "").toLowerCase().includes(q) ||
      (t.sector ?? "").toLowerCase().includes(q) ||
      (t.booking_ref ?? "").toLowerCase().includes(q)
    );
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const totalNetAmt = tickets.reduce((s, t) => s + (t.net_amt ?? 0), 0);
  const totalFare = tickets.reduce((s, t) => s + (t.sell_fare ?? 0), 0);
  const batches = new Set(tickets.map((t) => t.batch_id)).size;

  const allFilteredSelected =
    filtered.length > 0 && filtered.every((t) => selectedIds.has(t.id));
  const someSelected = selectedIds.size > 0;

  function toggleOne(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (allFilteredSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filtered.map((t) => t.id)));
    }
  }

  async function runCalculation(id: number) {
    setCalcLoading((prev) => ({ ...prev, [id]: true }));
    try {
      const { data } = await api.patch<RunCalcResult>(
        `/tickets/uploads/${id}/run-calculation`,
      );
      setTickets((prev) =>
        prev.map((t) =>
          t.id === id
            ? {
                ...t,
                matched_deal_id: data.matched_deal_id,
                matched_deal_type: data.matched_deal_type,
                matched_deal_name: data.matched_deal_name,
                calculated_incentive: data.calculated_incentive,
              }
            : t,
        ),
      );
    } catch {
      // silently keep existing state; user can retry
    } finally {
      setCalcLoading((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function openDealsModal(ticket: UploadedTicket) {
    setDealsLoading(true);
    try {
      const { data } = await api.get<DealMatchSummary[]>(
        `/tickets/uploads/${ticket.id}/matched-deals`,
      );
      setDealsModal({ ticket, deals: data });
    } catch {
      setDealsModal({ ticket, deals: [] });
    } finally {
      setDealsLoading(false);
    }
  }

  async function openDiagModal(ticket: UploadedTicket) {
    setDiagLoading((p) => ({ ...p, [ticket.id]: true }));
    try {
      const { data } = await api.get<MatchDiagnosis>(
        `/tickets/uploads/${ticket.id}/match-diagnosis`,
      );
      setDiagModal({ ticket, diagnosis: data });
    } catch {
      // open with empty deals so the user sees the trace header at least
    } finally {
      setDiagLoading((p) => ({ ...p, [ticket.id]: false }));
    }
  }

  function openEdit(ticket: UploadedTicket) {
    setEditForm({ ...ticket });
    setEditModal(ticket);
    setEditError("");
  }

  async function saveEdit() {
    if (!editModal) return;
    setEditSaving(true);
    setEditError("");
    try {
      const { data } = await api.patch<UploadedTicket>(
        `/tickets/uploads/${editModal.id}`,
        editForm,
      );
      setTickets((prev) => prev.map((t) => (t.id === data.id ? data : t)));
      setEditModal(null);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setEditError(msg ?? "Failed to save changes.");
    } finally {
      setEditSaving(false);
    }
  }

  async function deleteTicket() {
    if (!deleteConfirmId) return;
    setDeleteLoading(true);
    try {
      await api.delete(`/tickets/uploads/${deleteConfirmId}`);
      setTickets((prev) => prev.filter((t) => t.id !== deleteConfirmId));
      setDeleteConfirmId(null);
    } catch {
      // keep existing state; user can retry
    } finally {
      setDeleteLoading(false);
    }
  }

  async function runAllCalculation() {
    setBatchRunning(true);
    setBatchResult(null);
    try {
      if (selectedIds.size > 0) {
        let processed = 0,
          matched = 0,
          unmatched = 0,
          errors = 0;
        for (const id of selectedIds) {
          try {
            const { data } = await api.patch<RunCalcResult>(
              `/tickets/uploads/${id}/run-calculation`,
            );
            processed++;
            if (data.matched) matched++;
            else unmatched++;
            setTickets((prev) =>
              prev.map((t) =>
                t.id === id
                  ? {
                      ...t,
                      matched_deal_id: data.matched_deal_id,
                      matched_deal_type: data.matched_deal_type,
                      matched_deal_name: data.matched_deal_name,
                      calculated_incentive: data.calculated_incentive,
                    }
                  : t,
              ),
            );
          } catch {
            errors++;
          }
        }
        setBatchResult({ processed, matched, unmatched, errors });
        setSelectedIds(new Set());
      } else {
        const { data } = await api.patch<BatchRunCalcResult>(
          "/tickets/uploads/run-all-calculation",
        );
        setBatchResult(data);
        await fetchTickets();
      }
    } catch {
      // silently ignore; user can retry
    } finally {
      setBatchRunning(false);
    }
  }

  const TOTAL_COLS = TEXT_HEADERS.length + NUM_HEADERS.length + 7; // checkbox, CC, AccCode, Calc Incentive, Delta Comm, Matched Deal, Run Calc

  return (
    <>
      <div className="space-y-3">
        {/* header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">
              Tickets
            </h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Supplier statement tickets uploaded from XLS
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchTickets}
              disabled={loading}
              className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}
              />
            </button>
            <button
              onClick={runAllCalculation}
              disabled={batchRunning || !tickets.length}
              title={
                someSelected
                  ? `Run calc for ${selectedIds.size} selected ticket(s)`
                  : "Run calc for all tickets"
              }
              className="flex items-center gap-1.5 bg-amber-500 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-amber-600 disabled:opacity-50"
            >
              {batchRunning ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <PlayCircle className="w-3.5 h-3.5" />
              )}
              {batchRunning
                ? "Running…"
                : someSelected
                  ? `Run Calc (${selectedIds.size})`
                  : "Run All Calc"}
            </button>
            <Link
              href="/tickets/upload"
              className="flex items-center gap-1.5 bg-[#1e3a5f] text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[#16304f]"
            >
              <Upload className="w-3.5 h-3.5" /> Upload Tickets
            </Link>
          </div>
        </div>

        {/* batch result bar — separate row, no layout shift */}
        {batchResult && (
          <div className="flex items-center gap-4 px-4 py-2 bg-amber-50 border border-amber-200 rounded-lg text-[11px] text-gray-600">
            <span>
              Processed:{" "}
              <strong className="text-gray-900">{batchResult.processed}</strong>
            </span>
            <span className="text-green-700">
              Matched: <strong>{batchResult.matched}</strong>
            </span>
            <span className="text-gray-500">
              Unmatched: <strong>{batchResult.unmatched}</strong>
            </span>
            {batchResult.errors > 0 && (
              <span className="text-red-600">
                Errors: <strong>{batchResult.errors}</strong>
              </span>
            )}
            <button
              onClick={() => setBatchResult(null)}
              className="ml-auto text-gray-400 hover:text-gray-600 text-[10px]"
            >
              ✕ dismiss
            </button>
          </div>
        )}

        {/* stats */}
        <div className="grid grid-cols-4 gap-2">
          {[
            {
              label: "Total Tickets",
              value: tickets.length,
              color: "bg-blue-50 text-blue-700 border-blue-200",
            },
            {
              label: "Batches",
              value: batches,
              color: "bg-indigo-50 text-indigo-700 border-indigo-200",
            },
            {
              label: "Total Sell Fare",
              value: `₹ ${fmt(totalFare)}`,
              color: "bg-green-50 text-green-700 border-green-200",
            },
            {
              label: "Net Amount",
              value: `₹ ${fmt(totalNetAmt)}`,
              color: "bg-purple-50 text-purple-700 border-purple-200",
            },
          ].map((s) => (
            <div
              key={s.label}
              className={`rounded-xl border px-4 py-3 ${s.color}`}
            >
              <p className="text-lg font-bold leading-tight">{s.value}</p>
              <p className="text-[11px] font-medium mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        {/* search */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search ticket, PNR, passenger, airline, sector…"
              className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
          </div>
          <span className="text-[11px] text-gray-400 ml-auto whitespace-nowrap">
            {filtered.length} ticket{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="table-auto border-collapse">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  {/* checkbox */}
                  <th
                    className="px-3 py-2.5 text-center whitespace-nowrap sticky left-0"
                    style={{ background: "#1e3a5f" }}
                  >
                    <input
                      type="checkbox"
                      checked={allFilteredSelected}
                      onChange={toggleAll}
                      className="w-3.5 h-3.5 rounded border-gray-400 accent-amber-400 cursor-pointer"
                    />
                  </th>
                  {/* text columns */}
                  {TEXT_HEADERS.map((h) => (
                    <th
                      key={h.key}
                      className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap"
                    >
                      {h.label}
                    </th>
                  ))}
                  {/* numeric columns */}
                  {NUM_HEADERS.map((h) => (
                    <th
                      key={h.key}
                      className="px-3 py-2.5 text-right text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap"
                    >
                      {h.label}
                    </th>
                  ))}
                  {/* trailing text columns */}
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                    CC
                  </th>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                    Acc Code
                  </th>
                  {/* calculated incentive */}
                  <th className="px-3 py-2.5 text-right text-[10px] font-semibold text-amber-300 uppercase tracking-wider whitespace-nowrap">
                    Calc. Incentive
                  </th>
                  {/* delta comm */}
                  <th className="px-3 py-2.5 text-right text-[10px] font-semibold text-orange-300 uppercase tracking-wider whitespace-nowrap">
                    Delta Comm
                  </th>
                  {/* sold to */}
                  <th className="px-3 py-2.5 text-right text-[10px] font-semibold text-gray-300 uppercase tracking-wider whitespace-nowrap">
                    Sold to
                  </th>
                  {/* name */}
                  <th className="px-3 py-2.5 text-right text-[10px] font-semibold text-gray-300 uppercase tracking-wider whitespace-nowrap">
                    name
                  </th>
                  {/* deal match */}
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                    Matched Deal
                  </th>
                  {/* action */}
                  <th
                    className="px-3 py-2.5 text-center text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap sticky right-0"
                    style={{ background: "#1e3a5f" }}
                  >
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td
                      colSpan={TOTAL_COLS}
                      className="px-4 py-12 text-center text-xs text-gray-400"
                    >
                      <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />
                      Loading tickets…
                    </td>
                  </tr>
                ) : apiError ? (
                  <tr>
                    <td
                      colSpan={TOTAL_COLS}
                      className="px-4 py-10 text-center text-xs text-red-400"
                    >
                      {apiError}
                    </td>
                  </tr>
                ) : paginated.length === 0 ? (
                  <tr>
                    <td colSpan={TOTAL_COLS} className="px-4 py-14 text-center">
                      <div className="flex flex-col items-center gap-3">
                        <FileSpreadsheet className="w-8 h-8 text-gray-300" />
                        <p className="text-xs text-gray-400 font-medium">
                          {search
                            ? "No tickets match your search."
                            : "No tickets uploaded yet."}
                        </p>
                        {!search && (
                          <Link
                            href="/tickets/upload"
                            className="flex items-center gap-1.5 bg-[#1e3a5f] text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[#16304f]"
                          >
                            <Upload className="w-3 h-3" /> Upload First Batch
                          </Link>
                        )}
                      </div>
                    </td>
                  </tr>
                ) : (
                  paginated.map((t, idx) => {
                    const rowBg = idx % 2 === 0 ? "bg-white" : "bg-gray-50/30";
                    const isCalcLoading = calcLoading[t.id] ?? false;
                    const isSelected = selectedIds.has(t.id);
                    return (
                      <tr
                        key={t.id}
                        className={`border-b border-gray-100 hover:bg-blue-50/20 transition-colors ${isSelected ? "bg-amber-50/40" : rowBg}`}
                      >
                        {/* checkbox */}
                        <td
                          className={`px-3 py-2 text-center whitespace-nowrap sticky left-0 ${isSelected ? "bg-amber-50/40" : rowBg}`}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleOne(t.id)}
                            className="w-3.5 h-3.5 rounded border-gray-300 accent-amber-500 cursor-pointer"
                          />
                        </td>

                        {/* text columns */}
                        {TEXT_HEADERS.map((h) => {
                          const val = t[h.key] as string | null;
                          if (h.key === "airlines_code") {
                            return (
                              <td
                                key={h.key}
                                className="px-3 py-2 whitespace-nowrap"
                              >
                                {val ? (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
                                    {val}
                                  </span>
                                ) : (
                                  <span className="text-gray-300 text-[11px]">
                                    —
                                  </span>
                                )}
                              </td>
                            );
                          }
                          if (h.key === "booking_class") {
                            return (
                              <td
                                key={h.key}
                                className="px-3 py-2 whitespace-nowrap"
                              >
                                {val ? (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-gray-100 text-gray-700">
                                    {val}
                                  </span>
                                ) : (
                                  <span className="text-gray-300 text-[11px]">
                                    —
                                  </span>
                                )}
                              </td>
                            );
                          }
                          return (
                            <td
                              key={h.key}
                              className="px-3 py-2 text-[11px] text-gray-600 whitespace-nowrap"
                            >
                              {txt(val)}
                            </td>
                          );
                        })}

                        {/* numeric columns */}
                        {NUM_HEADERS.map((h) => {
                          const val = t[h.key] as number | null;
                          const isNet = h.key === "net_amt";
                          return (
                            <td
                              key={h.key}
                              className={`px-3 py-2 text-right text-[11px] whitespace-nowrap font-medium ${isNet ? "text-green-700" : "text-gray-700"}`}
                            >
                              {fmt(val)}
                            </td>
                          );
                        })}

                        {/* CC */}
                        <td className="px-3 py-2 text-[11px] text-gray-600 whitespace-nowrap">
                          {txt(t.cc)}
                        </td>
                        {/* Acc Code */}
                        <td className="px-3 py-2 text-[11px] text-gray-600 whitespace-nowrap">
                          {txt(t.acc_code)}
                        </td>

                        {/* Calculated Incentive */}
                        <td className="px-3 py-2 text-right text-[11px] whitespace-nowrap font-semibold">
                          {t.calculated_incentive != null ? (
                            <span className="text-amber-700">
                              ₹ {fmt(t.calculated_incentive)}
                            </span>
                          ) : (
                            <span className="text-gray-300">—</span>
                          )}
                        </td>

                        {/* Delta Comm = Comm Sell - Calc. Incentive */}
                        <td className="px-3 py-2 text-right text-[11px] whitespace-nowrap font-semibold">
                          {t.comm_sell != null &&
                          t.calculated_incentive != null ? (
                            (() => {
                              const delta =
                                (t.comm_sell ?? 0) -
                                (t.calculated_incentive ?? 0);
                              return (
                                <span
                                  className={
                                    delta >= 0
                                      ? "text-orange-600"
                                      : "text-red-600"
                                  }
                                >
                                  ₹ {fmt(delta)}
                                </span>
                              );
                            })()
                          ) : (
                            <span className="text-gray-300">—</span>
                          )}
                        </td>
                        {/* sold to */}
                        <td className="px-3 py-2 text-center text-[11px] whitespace-nowrap">
                          {t.sold_to ? (
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${t.sold_to === "agency" ? "bg-violet-50 text-violet-700 border-violet-200" : "bg-sky-50 text-sky-700 border-sky-200"}`}>
                              {t.sold_to}
                            </span>
                          ) : (
                            <span className="text-gray-300">—</span>
                          )}
                        </td>
                        {/* customer name */}
                        <td className="px-3 py-2 text-[11px] text-gray-600 whitespace-nowrap">
                          {t.customer_name ?? <span className="text-gray-300">—</span>}
                        </td>

                        {/* Matched Deal */}
                        <td className="px-3 py-2 whitespace-nowrap">
                          {t.matched_deal_name ? (
                            <button
                              onClick={() => openDealsModal(t)}
                              className="flex flex-col gap-0.5 text-left hover:opacity-80 transition-opacity cursor-pointer"
                              title="Click to see all matching deals"
                            >
                              <span className="font-mono text-[9px] font-bold text-gray-400">
                                {dealNo(t.matched_deal_type, t.matched_deal_id)}
                              </span>
                              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-50 text-green-700 border border-green-200">
                                <CheckCircle2 className="w-3 h-3" />
                                {t.matched_deal_name}
                              </span>
                              {t.matched_deal_type && (
                                <span
                                  className={`self-start px-1.5 py-0 rounded text-[9px] font-bold uppercase ${
                                    t.matched_deal_type === "b2b"
                                      ? "bg-violet-50 text-violet-600 border border-violet-200"
                                      : "bg-sky-50 text-sky-600 border border-sky-200"
                                  }`}
                                >
                                  {t.matched_deal_type}
                                </span>
                              )}
                            </button>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-400 border border-gray-200">
                              No Deal Found
                            </span>
                          )}
                        </td>

                        {/* Actions: Edit + Delete + Run Calc — sticky right */}
                        <td
                          className={`px-3 py-2 text-center whitespace-nowrap sticky right-0 ${isSelected ? "bg-amber-50/40" : rowBg}`}
                        >
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => openEdit(t)}
                              title="Edit ticket"
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border text-[10px] font-semibold transition-colors border-blue-300 text-blue-600 hover:bg-blue-600 hover:text-white"
                            >
                              <Pencil className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => setDeleteConfirmId(t.id)}
                              title="Delete ticket"
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border text-[10px] font-semibold transition-colors border-red-300 text-red-500 hover:bg-red-500 hover:text-white"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => openDiagModal(t)}
                              disabled={diagLoading[t.id]}
                              title="Diagnose deal matching — see step-by-step why this ticket did or did not match"
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border text-[10px] font-semibold transition-colors border-violet-300 text-violet-600 hover:bg-violet-600 hover:text-white disabled:opacity-50"
                            >
                              {diagLoading[t.id] ? (
                                <RefreshCw className="w-3 h-3 animate-spin" />
                              ) : (
                                <FileSearch className="w-3 h-3" />
                              )}
                            </button>
                            <button
                              onClick={() => runCalculation(t.id)}
                              disabled={isCalcLoading}
                              title="Match ticket against approved deals"
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-[10px] font-semibold transition-colors disabled:opacity-50 bg-white border-[#1e3a5f] text-[#1e3a5f] hover:bg-[#1e3a5f] hover:text-white"
                            >
                              {isCalcLoading ? (
                                <RefreshCw className="w-3 h-3 animate-spin" />
                              ) : (
                                <Calculator className="w-3 h-3" />
                              )}
                              {isCalcLoading ? "…" : "Run"}
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

          {/* pagination */}
          {totalPages > 1 && (
            <div className="px-4 py-2.5 border-t border-gray-100 flex items-center justify-between">
              <p className="text-[10px] text-gray-400">
                {Math.min((page - 1) * PAGE_SIZE + 1, filtered.length)}–
                {Math.min(page * PAGE_SIZE, filtered.length)} of{" "}
                <span className="font-semibold text-gray-600">
                  {filtered.length}
                </span>
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-2.5 py-1 rounded border border-gray-200 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                >
                  Previous
                </button>
                {Array.from(
                  { length: Math.min(totalPages, 7) },
                  (_, i) => i + 1,
                ).map((p) => (
                  <button
                    key={p}
                    onClick={() => setPage(p)}
                    className={`w-6 h-6 rounded-full text-[11px] font-medium border ${
                      p === page
                        ? "bg-[#1e3a5f] text-white border-[#1e3a5f]"
                        : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-2.5 py-1 rounded border border-gray-200 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Matched Deals Modal ────────────────────────────────────────── */}
      {dealsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col overflow-hidden">
            {/* header */}
            <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100">
              <div>
                <h2 className="text-sm font-bold text-gray-900">
                  Matching Deals
                </h2>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  Ticket{" "}
                  {dealsModal.ticket.ticket_number ??
                    dealsModal.ticket.booking_ref}{" "}
                  · {dealsModal.deals.length} deal
                  {dealsModal.deals.length !== 1 ? "s" : ""} found
                </p>
              </div>
              <button
                onClick={() => setDealsModal(null)}
                className="text-gray-400 hover:text-gray-700 text-lg leading-none"
              >
                ×
              </button>
            </div>

            {/* body */}
            <div className="overflow-y-auto flex-1 px-5 py-4">
              {dealsLoading ? (
                <div className="flex items-center justify-center py-10">
                  <RefreshCw className="w-5 h-5 animate-spin text-gray-300" />
                </div>
              ) : dealsModal.deals.length === 0 ? (
                <p className="text-xs text-gray-400 text-center py-8">
                  No matching deals found for this ticket.
                </p>
              ) : (
                <div className="space-y-2.5">
                  {dealsModal.deals.map((d) => (
                    <div
                      key={`${d.deal_type}-${d.deal_id}`}
                      className={`rounded-xl border p-3.5 ${d.is_best ? "border-green-300 bg-green-50/40" : "border-gray-100 bg-white"}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2 flex-wrap">
                          {d.is_best && (
                            <span className="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase bg-green-600 text-white">
                              Best
                            </span>
                          )}
                          <span className="font-mono text-[10px] font-bold text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200">
                            {d.deal_no}
                          </span>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border ${
                              d.deal_type === "b2b"
                                ? "bg-violet-50 text-violet-600 border-violet-200"
                                : d.deal_type === "airline"
                                  ? "bg-sky-50 text-sky-600 border-sky-200"
                                  : "bg-gray-50 text-gray-600 border-gray-200"
                            }`}
                          >
                            {d.deal_type}
                          </span>
                          <span className="text-[11px] font-semibold text-gray-800">
                            {d.deal_name}
                          </span>
                        </div>
                        <span
                          className={`text-xs font-bold tabular-nums whitespace-nowrap ${d.is_best ? "text-green-700" : "text-gray-700"}`}
                        >
                          {d.calculated_incentive != null
                            ? `₹ ${fmt(d.calculated_incentive)}`
                            : "—"}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-gray-500">
                        {d.valid_from && d.valid_to && (
                          <span>
                            {d.valid_from.slice(0, 10)} →{" "}
                            {d.valid_to.slice(0, 10)}
                          </span>
                        )}
                        {d.deal_maker_name && (
                          <span>Maker: {d.deal_maker_name}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* footer */}
            <div className="px-5 py-3 border-t border-gray-100 flex justify-end">
              <button
                onClick={() => setDealsModal(null)}
                className="px-4 py-1.5 rounded-lg bg-gray-100 text-gray-700 text-xs font-semibold hover:bg-gray-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Match Diagnosis Modal ────────────────────────────────────── */}
      {diagModal && (
        <DiagnosisModal
          ticket={diagModal.ticket}
          diagnosis={diagModal.diagnosis}
          onClose={() => setDiagModal(null)}
        />
      )}

      {/* ── Edit Ticket Modal ─────────────────────────────────────────── */}
      {editModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
            {/* header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
              <div>
                <h2 className="text-sm font-bold text-gray-900">Edit Ticket</h2>
                <p className="text-[11px] text-gray-400 mt-0.5">Ticket #{editModal.ticket_number ?? editModal.id}</p>
              </div>
              <button onClick={() => setEditModal(null)} className="p-1.5 rounded-lg hover:bg-gray-100">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>

            {/* body */}
            <div className="overflow-y-auto flex-1 px-5 py-4 space-y-5">
              {/* Passenger & Trip */}
              <div>
                <p className="text-[10px] font-bold text-[#1e3a5f] uppercase tracking-wide mb-2">Passenger &amp; Trip</p>
                <div className="grid grid-cols-2 gap-3">
                  {([
                    ["Ticket Number",    "ticket_number",      "text"],
                    ["Booking Ref",      "booking_ref",        "text"],
                    ["Last Name",        "last_name",          "text"],
                    ["First Name",       "first_name",         "text"],
                    ["Sector",           "sector",             "text"],
                    ["Booking Class",    "booking_class",      "text"],
                    ["Airline Name",     "airline_name",       "text"],
                    ["Airline Code",     "airlines_code",      "text"],
                    ["GDS PNR",          "gds_pnr",            "text"],
                    ["Ticket Date",      "ticket_date",        "text"],
                    ["Departure",        "departure_datetime", "text"],
                    ["Segment Type",     "segment_type",       "text"],
                    ["Invoice Type",     "invoice_type",       "text"],
                    ["Invoice No",       "invoice_no",         "text"],
                    ["CC",               "cc",                 "text"],
                    ["Acc Code",         "acc_code",           "text"],
                    ["Customer Name",    "customer_name",      "text"],
                  ] as [string, keyof UploadedTicket, string][]).map(([label, key]) => (
                    <div key={key}>
                      <label className="block text-[10px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>
                      <input
                        type="text"
                        value={(editForm[key] as string) ?? ""}
                        onChange={e => setEditForm(f => ({ ...f, [key]: e.target.value || null }))}
                        className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </div>
                  ))}
                  {/* Sold To — select */}
                  <div>
                    <label className="block text-[10px] font-medium text-gray-500 mb-1 uppercase tracking-wide">Sold To</label>
                    <select
                      value={editForm.sold_to ?? ""}
                      onChange={e => setEditForm(f => ({ ...f, sold_to: e.target.value || null }))}
                      className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
                    >
                      <option value="">— select —</option>
                      <option value="customer">Customer</option>
                      <option value="agency">Agency</option>
                    </select>
                  </div>
                </div>
              </div>

              {/* Amounts */}
              <div>
                <p className="text-[10px] font-bold text-[#1e3a5f] uppercase tracking-wide mb-2">Amounts</p>
                <div className="grid grid-cols-3 gap-3">
                  {([
                    ["Sell Fare",         "sell_fare"],
                    ["Sell Tax",          "sell_tax"],
                    ["Sell Tax YQ",       "sell_tax_yq"],
                    ["Sale YR",           "sale_yr"],
                    ["Sale K3",           "sale_k3"],
                    ["REI Sell",          "rei_sell"],
                    ["Seat Selection",    "seat_selection"],
                    ["Excess Baggage",    "excess_baggage"],
                    ["Meals",             "meals"],
                    ["RFD Sell",          "rfd_sell"],
                    ["CAN Charge",        "can_charge"],
                    ["Booking Fee",       "booking_fee_sell"],
                    ["CGST Sell",         "cgst_sell"],
                    ["SGST Sell",         "sgst_sell"],
                    ["IGST Sell",         "igst_sell"],
                    ["Comm Sell",         "comm_sell"],
                    ["ADM",               "adm"],
                    ["Incentive Sell",    "incentive_sell"],
                    ["DIS Sell",          "dis_sell"],
                    ["TDS Sell",          "tds_sell"],
                    ["Total Amt",         "total_amt"],
                    ["Paid By CC",        "paid_by_credit_card"],
                    ["Net AMT",           "net_amt"],
                  ] as [string, keyof UploadedTicket][]).map(([label, key]) => (
                    <div key={key}>
                      <label className="block text-[10px] font-medium text-gray-500 mb-1 uppercase tracking-wide">{label}</label>
                      <input
                        type="number"
                        step="0.01"
                        value={(editForm[key] as number) ?? ""}
                        onChange={e => setEditForm(f => ({ ...f, [key]: e.target.value === "" ? null : parseFloat(e.target.value) }))}
                        className="w-full border border-gray-200 rounded-md px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* footer */}
            <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between gap-3">
              {editError && (
                <div className="flex items-center gap-1.5 text-xs text-red-600">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />{editError}
                </div>
              )}
              <div className="flex gap-2 ml-auto">
                <button onClick={() => setEditModal(null)} className="px-4 py-1.5 rounded-lg border border-gray-200 text-gray-600 text-xs font-medium hover:bg-gray-50">
                  Cancel
                </button>
                <button onClick={saveEdit} disabled={editSaving} className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#1e3a5f] text-white text-xs font-semibold hover:bg-[#16304f] disabled:opacity-50">
                  {editSaving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  {editSaving ? "Saving…" : "Save Changes"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete Confirm Modal ──────────────────────────────────────── */}
      {deleteConfirmId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <Trash2 className="w-5 h-5 text-red-500" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-gray-900">Delete Ticket</h2>
                <p className="text-xs text-gray-500 mt-0.5">This action cannot be undone.</p>
              </div>
            </div>
            <p className="text-xs text-gray-600">
              Are you sure you want to permanently delete ticket ID <span className="font-semibold text-gray-900">#{deleteConfirmId}</span>?
            </p>
            <div className="flex gap-2 justify-end pt-1">
              <button onClick={() => setDeleteConfirmId(null)} className="px-4 py-1.5 rounded-lg border border-gray-200 text-gray-600 text-xs font-medium hover:bg-gray-50">
                Cancel
              </button>
              <button onClick={deleteTicket} disabled={deleteLoading} className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-red-500 text-white text-xs font-semibold hover:bg-red-600 disabled:opacity-50">
                {deleteLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                {deleteLoading ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
