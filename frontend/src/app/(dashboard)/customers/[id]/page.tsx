"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Edit2, RefreshCw, Contact, Ticket, FileText, Download, Trash2, Save, X, Eye } from "lucide-react";
import api from "@/lib/api";
import RetagPartyControl, {
  RetagBulkBar, RetagPayerControl, usePartyOptions, retagTickets, type RetagResult,
} from "@/components/billing/RetagPartyControl";
// Editing a customer lives in Employee Master (/user-master/employee-master);
// this page is the billing workspace and reads the record.
import { type Party as Customer } from "@/lib/party";
import { INCENTIVE_TYPE_COLS } from "@/lib/incentives";
import { splitGst, type GstTreatment, type PlaceOfSupply } from "@/lib/gstSplit";
import GstCells, { GstTotalCells } from "@/components/billing/GstCells";

type SoldTicket = {
  id: number;
  ticket_number: string | null;
  airline_name: string | null;
  airlines_code: string | null;
  first_name: string | null;
  last_name: string | null;
  pax_name: string | null;
  sector: string | null;
  booking_class: string | null;
  ticket_date: string | null;
  ticket_status: string | null;
  sell_fare: number | null;
  total_amt: number | null;
  calculated_incentive: number | null;
  incentive_breakdown: Record<string, number> | null;
  is_billed: boolean;
  billing_id: number | null;
  /** 'link' = the ticket names this party; 'name' = matched on the passenger's name. */
  matched_by?: string | null;
  /** Who flew and who pays, as stored. `corporate_id` set means the employer is
   *  billed and the ticket lives in Corporate Billing; cleared means the
   *  passenger is billed and it lives here. */
  customer_id?: number | null;
  corporate_id?: number | null;
  base_amount: number;
  markup_amount: number;
  gst_amount: number;
  /** The same tax as `gst_amount`, in the heads it is charged under. Exactly one
   *  side is non-zero, and all three are zero when the place of supply is
   *  unknown — `gst_treatment` says which of those a zero means. */
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  gst_treatment: GstTreatment | null;
  total_with_markup: number;
};

type SoldTicketsResponse = {
  customer: Customer;
  tickets: SoldTicket[];
  summary: {
    count: number; total_base: number; total_markup: number; total_gst: number;
    total_cgst: number; total_sgst: number; total_igst: number; total_with_markup: number;
  };
  /** Why these rows carry the heads they do — shown when it could not be decided. */
  place_of_supply: PlaceOfSupply | null;
};

type BillingListItem = {
  id: number;
  billing_name: string;
  period_from: string;
  period_to: string;
  total_base: number;
  total_markup: number;
  total_additional_markup: number;
  total_gst: number;
  total_cgst: number;
  total_sgst: number;
  total_igst: number;
  gst_treatment: GstTreatment | null;
  grand_total: number;
  item_count: number;
  created_at: string;
};

type BillingDetailLine = {
  ticket_id: number;
  ticket_number: string | null;
  airline_name: string | null;
  airlines_code: string | null;
  passenger: string | null;
  sector: string | null;
  ticket_date: string | null;
  base_amount: number;
  markup_amount: number;
  additional_markup: number;
  discount: number;
  gst_amount: number;
  // Absent on bills raised before the split — the API defaults them to 0 and
  // `gst_treatment` on the billing is NULL, which is what the screens branch on.
  cgst: number;
  sgst: number;
  igst: number;
  total: number;
};

type BillingDetail = {
  id: number;
  customer_id: number;
  billing_name: string;
  period_from: string;
  period_to: string;
  billing_type: string | null;
  total_base: number;
  total_markup: number;
  total_additional_markup: number;
  total_gst: number;
  total_cgst: number;
  total_sgst: number;
  total_igst: number;
  /** The place-of-supply decision this bill was RAISED under. Editing re-applies
   *  it rather than re-deciding, so an issued invoice cannot move between
   *  CGST + SGST and IGST because the party's address changed afterwards. */
  gst_treatment: GstTreatment | null;
  supplier_state_code: string | null;
  place_of_supply_code: string | null;
  grand_total: number;
  line_items: BillingDetailLine[];
  created_at: string;
};

const TABS = ["Customer Details", "Sold Tickets", "Billing Info"] as const;
type Tab = (typeof TABS)[number];

const money = (n: number | null | undefined) =>
  n == null ? "—" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

function markupLabel(c: Customer): string {
  if (c.markup_value == null || !c.markup_type) return "—";
  return c.markup_type === "percentage" ? `${c.markup_value}%` : `₹${c.markup_value}`;
}

function passengerName(t: SoldTicket): string {
  return t.pax_name || [t.first_name, t.last_name].filter(Boolean).join(" ") || "—";
}

/**
 * A ticket's issue date as `YYYY-MM-DD`, or "" if it cannot be read.
 *
 * `ticket_date` is a String(50) carried straight from whatever spreadsheet the ticket
 * arrived on — ticket_extraction normalises what it can and deliberately stores the rest
 * verbatim — so it is not reliably a date at all. This mirrors
 * backend/app/services/billing_calc.py::safe_date, which is the function that decides
 * which tickets a date filter keeps.
 *
 * NEVER FALL BACK TO `new Date(s)`. JavaScript reads "03/04/2026" as 4 March, the US
 * month-first order; the backend reads the same string as 3 April
 * (`dateutil.parse(..., dayfirst=True)`). A parser that silently disagrees with the
 * server about the same string is worse than one that admits defeat — this value ends up
 * as the period printed on an invoice. Hence the explicit day-first branch below, and ""
 * for anything that does not match it.
 */
function ticketDateISO(raw: string | null): string {
  if (!raw) return "";
  const s = raw.trim();
  if (!s) return "";

  // A real calendar date, or "". Date.parse is no use as a validator here: it happily
  // rolls 2026-02-31 over into 3 March, so the parts are checked back out of the Date.
  const build = (y: number, mo: number, d: number): string => {
    if (!(y >= 1900 && y <= 2999) || mo < 1 || mo > 12 || d < 1 || d > 31) return "";
    const dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return "";
    return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  };

  // Year-first: the ISO prefix every LCC-projected row carries, and the slash variant.
  const ymd = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/.exec(s);
  if (ymd) return build(Number(ymd[1]), Number(ymd[2]), Number(ymd[3]));

  // Day-first d/m/y, matching the backend. Two-digit years are 20xx.
  const dmy = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$/.exec(s);
  if (dmy) {
    const year = dmy[3].length === 2 ? 2000 + Number(dmy[3]) : Number(dmy[3]);
    return build(year, Number(dmy[2]), Number(dmy[1]));
  }
  return "";
}

/**
 * The span the selected tickets actually cover — the truest period for their bill.
 * Plain string comparison is correct because every value is `YYYY-MM-DD`; no Date
 * objects, so no timezone can shift a boundary.
 */
function periodFromTickets(rows: SoldTicket[]): { from: string; to: string; undated: number } {
  const dates = rows.map((t) => ticketDateISO(t.ticket_date)).filter(Boolean).sort();
  return {
    from: dates[0] ?? "",
    to: dates[dates.length - 1] ?? "",
    undated: rows.length - dates.length,
  };
}

/** Recompute one row with the customer markup + the entered additional (flat) markup.
 *
 *  The tax comes from lib/gstSplit, the mirror of the server's billing_calc, so
 *  the live preview and the saved invoice cannot disagree. `treatment` is the
 *  row's own — the server decided it from the two parties' GSTINs; the browser
 *  only applies it. */
function rowCalc(
  t: SoldTicket, additionalStr: string, discountStr: string, billingType: Customer["billing_type"],
) {
  const base = t.base_amount;
  const custMarkup = t.markup_amount;
  const addl = parseFloat(additionalStr) || 0;
  const disc = parseFloat(discountStr) || 0;
  const totalMarkup = custMarkup + addl;
  // Discount reduces the taxable value first, then GST applies on the reduced amount.
  const g = splitGst(base, totalMarkup, billingType, disc, t.gst_treatment);
  const total = base + totalMarkup - disc + g.gst;
  return { base, custMarkup, addl, disc, totalMarkup, gst: g.gst, split: g, total };
}

/** Recompute a saved billing line when its additional markup is being edited (base markup preserved). */
function editRowCalc(it: BillingDetailLine, additionalStr: string, billing: BillingDetail | null) {
  const base = it.base_amount;
  const markup = it.markup_amount;
  const addl = parseFloat(additionalStr) || 0;
  const disc = it.discount ?? 0;   // discount is preserved from creation (not edited here)
  const totalMarkup = markup + addl;
  // The treatment the BILLING was raised under, not the party's current address.
  const g = splitGst(base, totalMarkup, billing?.billing_type ?? null, disc, billing?.gst_treatment);
  const total = base + totalMarkup - disc + g.gst;
  return { base, addl, markup, gst: g.gst, split: g, total };
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-0.5">{label}</p>
      <p className="text-sm text-gray-800">{value || "—"}</p>
    </div>
  );
}

export default function CustomerDetailPage() {
  const params = useParams();
  const router = useRouter();
  const customerId = params.id as string;

  const [customer, setCustomer] = useState<Customer | null>(null);
  const [loadingCustomer, setLoadingCustomer] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Customer Details");

  // Sold Tickets
  const [dateField, setDateField] = useState<"ticket" | "travel">("ticket");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [soldTickets, setSoldTickets] = useState<SoldTicket[] | null>(null);
  // Which GST heads this party's supplies carry, and why — decided server-side
  // from the two GSTINs. One answer for the whole list: it is a fact about the
  // two parties, not about any one ticket.
  const [placeOfSupply, setPlaceOfSupply] = useState<PlaceOfSupply | null>(null);
  const [loadingTickets, setLoadingTickets] = useState(false);
  const [ticketsError, setTicketsError] = useState<string | null>(null);
  const [additional, setAdditional] = useState<Record<number, string>>({});
  const [discounts, setDiscounts] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Save Billing. The period is its own state, not the filter dates: the filter is now
  // optional, but `billings.period_from/to` are NOT NULL and get printed on the invoice.
  const [showSaveBilling, setShowSaveBilling] = useState(false);
  const [billingName, setBillingName] = useState("");
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [periodUndated, setPeriodUndated] = useState(0);
  const [savingBilling, setSavingBilling] = useState(false);

  // Billing Info
  const [billings, setBillings] = useState<BillingListItem[]>([]);
  const [loadingBillings, setLoadingBillings] = useState(false);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [viewBilling, setViewBilling] = useState<BillingDetail | null>(null);
  const [loadingViewId, setLoadingViewId] = useState<number | null>(null);
  const [editBilling, setEditBilling] = useState<BillingDetail | null>(null);
  const [loadingEditId, setLoadingEditId] = useState<number | null>(null);
  const [addlEdits, setAddlEdits] = useState<Record<number, string>>({});
  const [savingEdit, setSavingEdit] = useState(false);

  const fetchCustomer = useCallback(async () => {
    setLoadingCustomer(true);
    setError(null);
    try {
      const { data } = await api.get<Customer>(`/customers/${customerId}`);
      setCustomer(data);
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      setError(status === 404 ? "Customer not found." : "Failed to load customer.");
    } finally {
      setLoadingCustomer(false);
    }
  }, [customerId]);

  const fetchBillings = useCallback(async () => {
    setLoadingBillings(true);
    try {
      const { data } = await api.get<BillingListItem[]>(`/customers/${customerId}/billings`);
      setBillings(data);
    } catch {
      /* ignore */
    } finally {
      setLoadingBillings(false);
    }
  }, [customerId]);

  useEffect(() => {
    fetchCustomer();
    fetchBillings();
  }, [fetchCustomer, fetchBillings]);

  /**
   * Load this customer's tickets, matched to their passenger name.
   * Twin of corporates/[id]/page.tsx — keep the two in step.
   *
   * The date range is an optional NARROWING, not a precondition: leave it blank and you
   * get everything, which is what the API has always done (`if date_from or date_to:`)
   * and what Agency Billing has always offered. A range also drops tickets whose date
   * cannot be parsed, so clearing the dates is the only way to see undated tickets.
   */
  const applyRange = useCallback(async () => {
    if (dateFrom && dateTo && dateFrom > dateTo) {
      setTicketsError("From date must be before To date.");
      return;
    }
    setLoadingTickets(true);
    setTicketsError(null);
    try {
      const params: Record<string, string> = { date_field: dateField };
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const { data } = await api.get<SoldTicketsResponse>(`/customers/${customerId}/sold-tickets`, { params });
      setSoldTickets(data.tickets);
      setPlaceOfSupply(data.place_of_supply ?? null);
      setAdditional({});
      setDiscounts({});
      setSelected(new Set());
    } catch {
      setTicketsError("Failed to load tickets.");
    } finally {
      setLoadingTickets(false);
    }
  }, [customerId, dateFrom, dateTo, dateField]);

  // Load once, the first time the tab is actually opened — not on mount, because the
  // page lands on Details and this fetch is unpaginated. A ref guard rather than
  // depending on `applyRange`, which is memoised on the dates: depending on it would
  // refire on every keystroke in a date box and wipe the ticks and markups being typed.
  const ticketsLoaded = useRef(false);
  useEffect(() => {
    if (tab !== "Sold Tickets" || ticketsLoaded.current) return;
    ticketsLoaded.current = true;
    applyRange();
  }, [tab, applyRange]);

  /** "" when no range is set, which is now the default and means "everything". */
  const rangeLabel = dateFrom && dateTo ? `${dateFrom} → ${dateTo}`
    : dateFrom ? `from ${dateFrom}`
    : dateTo ? `up to ${dateTo}`
    : "";

  // Live summary over the loaded tickets + entered additional markups.
  const summary = useMemo(() => {
    const rows = soldTickets ?? [];
    let base = 0,
      markup = 0,
      addl = 0,
      gst = 0,
      cgst = 0,
      sgst = 0,
      igst = 0,
      total = 0;
    for (const t of rows) {
      const c = rowCalc(t, additional[t.id] ?? "", discounts[t.id] ?? "", customer?.billing_type ?? null);
      base += c.base;
      markup += c.custMarkup;
      addl += c.addl;
      gst += c.gst;
      cgst += c.split.cgst;
      sgst += c.split.sgst;
      igst += c.split.igst;
      total += c.total;
    }
    return { count: rows.length, base, markup, addl, gst, cgst, sgst, igst, total };
  }, [soldTickets, additional, discounts, customer]);

  // Who a ticket can be moved to. Loaded once here rather than per row, so a
  // 200-row table makes two requests instead of four hundred.
  const { options: partyOptions, employerOf } = usePartyOptions();
  const [retagBusy, setRetagBusy] = useState(false);
  const [retagNote, setRetagNote] = useState("");

  // A re-tagged ticket LEAVES this party's list — that is what the move means.
  // Say where it went, or a row vanishing reads as data loss.
  const afterRetag = useCallback((r: RetagResult) => {
    setTicketsError("");
    setRetagNote(
      r.untagged
        ? `${r.updated} ticket${r.updated === 1 ? "" : "s"} no longer tagged to anyone — they now match on passenger name alone.`
        : `${r.updated} ticket${r.updated === 1 ? "" : "s"} moved to ${r.party_name ?? "the selected party"}.`,
    );
    setSelected(new Set());
    applyRange();
  }, [applyRange]);

  const bulkRetag = useCallback(async (opt: Parameters<typeof retagTickets>[1]) => {
    // Billed rows are locked, and the endpoint refuses the whole batch if one
    // slips in, so filter them out here rather than letting it fail.
    const ids = (soldTickets ?? []).filter(t => selected.has(t.id) && !t.is_billed).map(t => t.id);
    if (ids.length === 0) { setTicketsError("Those rows are already billed, so they cannot be moved."); return; }
    setRetagBusy(true);
    try {
      afterRetag(await retagTickets(ids, opt));
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setTicketsError(typeof d === "string" ? d : "Could not move these tickets.");
    } finally { setRetagBusy(false); }
  }, [soldTickets, selected, afterRetag]);

  // Ids of rows that can be selected (already-billed tickets are locked).
  const selectableIds = useMemo(
    () => (soldTickets ?? []).filter((t) => !t.is_billed).map((t) => t.id),
    [soldTickets],
  );
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const toggleRow = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(selectableIds));

  // Totals over the SELECTED rows only (what a Save Billing will actually bill).
  const selectedSummary = useMemo(() => {
    const rows = (soldTickets ?? []).filter((t) => selected.has(t.id));
    let total = 0;
    for (const t of rows) total += rowCalc(t, additional[t.id] ?? "", discounts[t.id] ?? "", customer?.billing_type ?? null).total;
    return { count: rows.length, total };
  }, [soldTickets, selected, additional, discounts, customer]);

  // Live totals for the Billing edit popup (markup being edited per ticket).
  const editTotals = useMemo(() => {
    const items = editBilling?.line_items ?? [];
    let base = 0,
      markup = 0,
      addl = 0,
      gst = 0,
      cgst = 0,
      sgst = 0,
      igst = 0,
      total = 0;
    for (const it of items) {
      const c = editRowCalc(it, addlEdits[it.ticket_id] ?? "", editBilling);
      base += c.base;
      markup += c.markup;
      addl += c.addl;
      gst += c.gst;
      cgst += c.split.cgst;
      sgst += c.split.sgst;
      igst += c.split.igst;
      total += c.total;
    }
    return { base, markup, addl, gst, cgst, sgst, igst, total };
  }, [editBilling, addlEdits]);

  /**
   * Open the save dialog, seeding the invoice period.
   *
   * A filter range, when the user set one — that is what this dialog has always shown.
   * Otherwise the span the SELECTED tickets actually cover, which is a truer period than
   * an arbitrary filter window anyway. Either way it stays editable.
   */
  const openSaveBilling = () => {
    const rows = (soldTickets ?? []).filter((t) => selected.has(t.id) && !t.is_billed);
    const span = periodFromTickets(rows);
    setPeriodFrom(dateFrom || span.from);
    setPeriodTo(dateTo || span.to);
    setPeriodUndated(dateFrom && dateTo ? 0 : span.undated);
    setShowSaveBilling(true);
  };

  const saveBilling = async () => {
    const rows = (soldTickets ?? []).filter((t) => selected.has(t.id) && !t.is_billed);
    if (!billingName.trim() || rows.length === 0) return;
    if (!periodFrom || !periodTo || periodFrom > periodTo) return;
    setSavingBilling(true);
    try {
      await api.post(`/customers/${customerId}/billings`, {
        billing_name: billingName.trim(),
        period_from: periodFrom,
        period_to: periodTo,
        items: rows.map((t) => ({
          ticket_id: t.id,
          additional_markup: parseFloat(additional[t.id] ?? "") || 0,
          discount: parseFloat(discounts[t.id] ?? "") || 0,
        })),
      });
      setShowSaveBilling(false);
      setBillingName("");
      setSelected(new Set());
      fetchBillings();
      // Refresh the tickets so the just-billed rows show as "Billed".
      applyRange();
      setTab("Billing Info");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg ?? "Failed to save billing.");
    } finally {
      setSavingBilling(false);
    }
  };

  const openView = async (b: BillingListItem) => {
    setLoadingViewId(b.id);
    try {
      const { data } = await api.get<BillingDetail>(`/customers/${customerId}/billings/${b.id}`);
      setViewBilling(data);
    } catch {
      alert("Failed to load billing.");
    } finally {
      setLoadingViewId(null);
    }
  };

  const openEdit = async (b: BillingListItem) => {
    setLoadingEditId(b.id);
    try {
      const { data } = await api.get<BillingDetail>(`/customers/${customerId}/billings/${b.id}`);
      setEditBilling(data);
      setAddlEdits(Object.fromEntries(data.line_items.map((it) => [it.ticket_id, String(it.additional_markup)])));
    } catch {
      alert("Failed to load billing.");
    } finally {
      setLoadingEditId(null);
    }
  };

  const saveEdit = async () => {
    if (!editBilling) return;
    setSavingEdit(true);
    try {
      await api.patch(`/customers/${customerId}/billings/${editBilling.id}`, {
        items: editBilling.line_items.map((it) => ({
          ticket_id: it.ticket_id,
          additional_markup: parseFloat(addlEdits[it.ticket_id] ?? "") || 0,
        })),
      });
      setEditBilling(null);
      fetchBillings();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg ?? "Failed to update billing.");
    } finally {
      setSavingEdit(false);
    }
  };

  const downloadPdf = async (id: number) => {
    setDownloadingId(id);
    try {
      const res = await api.get(`/customers/${customerId}/billings/${id}/pdf`, { responseType: "blob" });
      const url = window.URL.createObjectURL(res.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `billing-${id}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      alert("Failed to download PDF.");
    } finally {
      setDownloadingId(null);
    }
  };

  const deleteBilling = async (b: BillingListItem) => {
    if (!window.confirm(`Delete billing "${b.billing_name}"?`)) return;
    try {
      await api.delete(`/customers/${customerId}/billings/${b.id}`);
      fetchBillings();
    } catch {
      alert("Failed to delete billing.");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <button onClick={() => router.push("/customers")} className="mt-1 p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50">
            <ArrowLeft className="w-4 h-4 text-gray-600" />
          </button>
          <div>
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Customer Billing</p>
            <h1 className="text-xl font-bold text-gray-900">
              {customer ? `${customer.first_name} ${customer.last_name ?? ""}`.trim() : "Customer"}
            </h1>
            {customer?.company && <p className="text-xs text-gray-500 mt-0.5">{customer.company}</p>}
          </div>
        </div>
        {customer && (
          <Link
            href="/user-master/employee-master"
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50"
          >
            <Edit2 className="w-3.5 h-3.5" /> Edit in Employee Master
          </Link>
        )}
      </div>

      {/* Tab bar */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="flex">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2.5 text-[11px] font-semibold whitespace-nowrap border-b-2 transition-colors flex items-center gap-1.5 ${
                tab === t ? "border-[#1e3a5f] text-[#1e3a5f] bg-blue-50/40" : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t === "Customer Details" ? <Contact className="w-3.5 h-3.5" /> : t === "Sold Tickets" ? <Ticket className="w-3.5 h-3.5" /> : <FileText className="w-3.5 h-3.5" />}
              {t}
              {t === "Billing Info" && billings.length > 0 && (
                <span className="ml-1 bg-gray-100 text-gray-600 text-[9px] font-bold px-1.5 py-0.5 rounded-full">{billings.length}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="px-4 py-3 text-xs text-red-500 bg-red-50 border border-red-100 rounded-lg">{error}</div>}

      {loadingCustomer ? (
        <div className="flex items-center justify-center py-24 bg-white rounded-xl border border-gray-100">
          <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        </div>
      ) : !customer ? null : tab === "Customer Details" ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-5">
            <DetailRow label="First Name" value={customer.first_name} />
            <DetailRow label="Last Name" value={customer.last_name} />
            <DetailRow label="Company" value={customer.company} />
            <DetailRow label="Title" value={customer.title} />
            <DetailRow label="Phone / Contact" value={customer.phone} />
            <DetailRow label="Email" value={customer.email} />
            <DetailRow label="GST Registration" value={customer.gst_registered ? "Registered" : "Unregistered"} />
            <DetailRow label="GST No" value={customer.gst_registered ? customer.gst_no : "—"} />
            <DetailRow label="PAN No" value={customer.pan_no} />
            <DetailRow label="Markup Type" value={customer.markup_type ? customer.markup_type.charAt(0).toUpperCase() + customer.markup_type.slice(1) : "—"} />
            <DetailRow label="Markup" value={markupLabel(customer)} />
            <DetailRow
              label="Billing Type"
              value={customer.billing_type ? customer.billing_type.charAt(0).toUpperCase() + customer.billing_type.slice(1) : "—"}
            />
            <DetailRow label="Status" value={customer.is_active ? "Active" : "Inactive"} />
          </div>
        </div>
      ) : tab === "Sold Tickets" ? (
        <div className="space-y-3">
          {/* Date range bar */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex flex-wrap items-end gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Date type</label>
              <select
                value={dateField}
                onChange={(e) => setDateField(e.target.value as "ticket" | "travel")}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
              >
                <option value="ticket">Ticket date</option>
                <option value="travel">Travel date</option>
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">From</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
              />
            </div>
            <button
              onClick={() => applyRange()}
              disabled={loadingTickets}
              className="bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50"
            >
              {loadingTickets ? "Loading…" : "Apply"}
            </button>
            {(dateFrom || dateTo) && (
              <button
                onClick={() => { setDateFrom(""); setDateTo(""); }}
                disabled={loadingTickets}
                className="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-700 pb-2.5 disabled:opacity-50"
                title="Clear the dates, then press Apply to see every ticket"
              >
                <X className="w-3 h-3" /> Clear dates
              </button>
            )}
            <p className="basis-full text-[11px] text-gray-400 -mt-1">
              Leave the dates blank to see every ticket — a range only narrows the list,
              and also hides any ticket whose date cannot be read.
            </p>
            {soldTickets && soldTickets.length > 0 && (
              <button
                onClick={() => { openSaveBilling(); }}
                disabled={selected.size === 0}
                className="ml-auto flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Save className="w-4 h-4" /> Save Billing{selected.size > 0 ? ` (${selected.size})` : ""}
              </button>
            )}
          </div>

          {retagNote && (
            <div className="px-4 py-3 text-xs text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-lg flex items-center justify-between gap-3">
              <span>{retagNote}</span>
              <button onClick={() => setRetagNote("")} className="text-emerald-600 hover:text-emerald-800 text-[11px] font-semibold">Dismiss</button>
            </div>
          )}

          <RetagBulkBar
            count={(soldTickets ?? []).filter(t => selected.has(t.id) && !t.is_billed).length}
            options={partyOptions}
            busy={retagBusy}
            onApply={bulkRetag}
          />

          {ticketsError && <div className="px-4 py-3 text-xs text-red-500 bg-red-50 border border-red-100 rounded-lg">{ticketsError}</div>}

          {loadingTickets ? (
            <div className="flex items-center justify-center py-20 bg-white rounded-xl border border-gray-100">
              <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
            </div>
          ) : soldTickets === null ? (
            <div className="flex flex-col items-center justify-center py-20 bg-white rounded-xl border border-gray-100 text-center">
              <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                <Ticket className="w-7 h-7 text-gray-300" />
              </div>
              <p className="text-sm font-medium text-gray-600">Could not load tickets</p>
              <p className="text-xs text-gray-400 mt-1">Press Apply to try again.</p>
            </div>
          ) : (
            <>
              {/* Summary cards. The GST card is replaced by the head that
                  actually applies — showing CGST, SGST and IGST side by side
                  would imply a supply carries all three, and no supply does. */}
              <div className="grid grid-cols-2 md:grid-cols-7 gap-3">
                {[
                  { label: "Tickets", value: String(summary.count) },
                  { label: "Total Base", value: money(summary.base) },
                  { label: "Total Markup", value: money(summary.markup) },
                  { label: "Total Additional", value: money(summary.addl) },
                  ...(placeOfSupply?.treatment === "igst"
                    ? [{ label: "Total IGST (18%)", value: money(summary.igst) }]
                    : placeOfSupply?.treatment === "cgst_sgst"
                      ? [
                          { label: "Total CGST (9%)", value: money(summary.cgst) },
                          { label: "Total SGST (9%)", value: money(summary.sgst) },
                        ]
                      : [{ label: "Total GST (18%)", value: money(summary.gst) }]),
                  { label: "Grand Total", value: money(summary.total) },
                ].map((s) => (
                  <div key={s.label} className="bg-white rounded-xl border border-gray-100 px-4 py-3 shadow-sm">
                    <p className="text-sm font-bold text-gray-900 leading-none">{s.value}</p>
                    <p className="text-[11px] text-gray-400 mt-1">{s.label}</p>
                  </div>
                ))}
              </div>

              {/* Why these rows carry the heads they do. Shown always when
                  decided (one line, so an invoice can be checked at a glance)
                  and as a warning when not — an empty CGST column with no
                  explanation just looks broken. */}
              {placeOfSupply && (
                <div
                  className={`px-4 py-2.5 rounded-lg border text-[11px] ${
                    placeOfSupply.decided
                      ? "bg-blue-50 border-blue-100 text-blue-800"
                      : "bg-amber-50 border-amber-100 text-amber-800"
                  }`}
                >
                  <span className="font-semibold">
                    {placeOfSupply.decided ? "Place of supply: " : "GST not split: "}
                  </span>
                  {placeOfSupply.note}
                  {!placeOfSupply.decided && (
                    <span className="ml-1">
                      The GST above is still charged and included in the totals — it just
                      cannot be attributed to CGST/SGST or IGST yet.
                    </span>
                  )}
                </div>
              )}

              <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-100">
                  <p className="text-xs font-semibold text-gray-700">
                    {rangeLabel
                      ? `${soldTickets.length} tickets by ${dateField === "travel" ? "travel" : "issue"} date ${rangeLabel} for `
                      : `All ${soldTickets.length} tickets for `}
                    {customer.first_name} {customer.last_name ?? ""}
                  </p>
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    Markup: {markupLabel(customer)}
                    {customer.markup_type ? ` (${customer.markup_type})` : ""} · Billing:{" "}
                    {customer.billing_type
                      ? `${customer.billing_type} — 18% GST on ${customer.billing_type === "reseller" ? "gross + markup" : "markup only"}`
                      : "not set — no GST applied"}
                    . Edit Additional Markup to recalculate. Totals above cover every row
                    shown, tickets already billed included; Save Billing charges only the
                    rows you tick.
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr style={{ background: "#1e3a5f" }}>
                        <th className="px-3 py-2.5 text-center">
                          <input
                            type="checkbox"
                            checked={allSelected}
                            onChange={toggleAll}
                            disabled={selectableIds.length === 0}
                            title="Select all unbilled"
                            className="accent-emerald-500 cursor-pointer align-middle"
                          />
                        </th>
                        {["TICKET #", "AIRLINE", "CODE", "PASSENGER", "SECTOR", "DATE", "TOTAL FARE", "MARKUP", "ADD. MARKUP", "DISCOUNT", "CGST", "SGST", "IGST", "TOTAL BILLING", "STATUS", "MATCHED", "CORPORATE"].map((h) => (
                          <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                            {h}
                          </th>
                        ))}
                        {INCENTIVE_TYPE_COLS.map((col) => (
                          <th key={col.key} className="px-3 py-2.5 text-right text-[10px] font-semibold text-white/90 uppercase tracking-wider whitespace-nowrap border-l border-white/10">
                            {col.label}
                          </th>
                        ))}
                        <th className="px-3 py-2.5 text-right text-[10px] font-bold text-white uppercase tracking-wider whitespace-nowrap border-l-2 border-white/30">
                          Total Inc.
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {soldTickets.length === 0 ? (
                        <tr>
                          {/* 30 = checkbox + 17 named + 11 incentive + Total Inc. */}
                          <td colSpan={30} className="px-4 py-16 text-center">
                            <div className="flex flex-col items-center justify-center">
                              <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                                <Ticket className="w-7 h-7 text-gray-300" />
                              </div>
                              <p className="text-sm font-medium text-gray-600">
                                {rangeLabel ? "No tickets in this date range" : "No tickets for this customer yet"}
                              </p>
                              <p className="text-xs text-gray-400 mt-1">
                                {rangeLabel
                                  ? `No tickets matched this customer's name ${rangeLabel}. Clear the dates to see every ticket.`
                                  : "No uploaded ticket is tagged to this customer or matches their passenger name."}
                              </p>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        soldTickets.map((t, idx) => {
                          const c = rowCalc(t, additional[t.id] ?? "", discounts[t.id] ?? "", customer.billing_type);
                          const totalInc = INCENTIVE_TYPE_COLS.reduce((s, col) => s + (t.incentive_breakdown?.[col.key] ?? 0), 0);
                          const isSel = selected.has(t.id);
                          return (
                            <tr key={t.id} className={`border-b border-gray-50 hover:bg-blue-50/30 ${isSel ? "bg-emerald-50/40" : idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                              <td className="px-3 py-2 text-center">
                                <input
                                  type="checkbox"
                                  checked={isSel}
                                  disabled={t.is_billed}
                                  onChange={() => toggleRow(t.id)}
                                  title={t.is_billed ? "Already billed" : undefined}
                                  className="accent-emerald-500 cursor-pointer align-middle disabled:cursor-not-allowed disabled:opacity-40"
                                />
                              </td>
                              <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{t.ticket_number ?? "—"}</td>
                              <td className="px-3 py-2 text-[11px] text-gray-600">{t.airline_name ?? "—"}</td>
                              <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{t.airlines_code ?? "—"}</td>
                              <td className="px-3 py-2 text-[11px] text-gray-600">{passengerName(t)}</td>
                              <td className="px-3 py-2 text-[11px] text-gray-500">{t.sector ?? "—"}</td>
                              <td className="px-3 py-2 text-[11px] text-gray-500">{t.ticket_date ?? "—"}</td>
                              <td className="px-3 py-2 text-[11px] text-gray-600">{money(c.base)}</td>
                              <td className="px-3 py-2 text-[11px] font-semibold text-emerald-600">{money(c.custMarkup)}</td>
                              <td className="px-3 py-2">
                                <input
                                  type="number"
                                  step="any"
                                  value={additional[t.id] ?? ""}
                                  onChange={(e) => setAdditional((prev) => ({ ...prev, [t.id]: e.target.value }))}
                                  placeholder="0"
                                  className="w-24 border border-gray-200 rounded px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-white"
                                />
                              </td>
                              <td className="px-3 py-2">
                                <input
                                  type="number"
                                  step="any"
                                  value={discounts[t.id] ?? ""}
                                  onChange={(e) => setDiscounts((prev) => ({ ...prev, [t.id]: e.target.value }))}
                                  placeholder="0"
                                  className="w-24 border border-gray-200 rounded px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-rose-400/50 bg-white"
                                />
                              </td>
                              <GstCells split={c.split} />
                              <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{money(c.total)}</td>
                              <td className="px-3 py-2 whitespace-nowrap">
                                {t.is_billed ? (
                                  <span className="inline-block bg-emerald-50 text-emerald-700 text-[10px] font-semibold px-2 py-0.5 rounded-full border border-emerald-200">Billed</span>
                                ) : (
                                  <span className="inline-block bg-gray-100 text-gray-500 text-[10px] font-semibold px-2 py-0.5 rounded-full">Not Billed</span>
                                )}
                              </td>
                              {/* Why this row is here: the ticket explicitly names this
                                  party, or nobody claimed it and the passenger's name
                                  matched. Name matching is the fuzzy one, so say which. */}
                              <td className="px-3 py-2 whitespace-nowrap">
                                <div className="flex flex-col gap-1">
                                  {t.matched_by === "link" ? (
                                    <span title="This ticket is tagged to this party"
                                      className="inline-block w-fit bg-sky-50 text-sky-700 text-[10px] font-semibold px-2 py-0.5 rounded-full border border-sky-200">Tagged</span>
                                  ) : t.matched_by === "name" ? (
                                    <span title="No party is tagged on this ticket; the passenger's name matched"
                                      className="inline-block w-fit bg-gray-50 text-gray-500 text-[10px] font-semibold px-2 py-0.5 rounded-full border border-gray-200">By name</span>
                                  ) : (
                                    <span className="text-gray-300 text-[10px]">—</span>
                                  )}
                                  {/* Billing this elsewhere is a correction, not an edit
                                      of the ticket, so it belongs beside "who claimed
                                      this" rather than in a form. */}
                                  <div className="min-w-44">
                                    <RetagPartyControl
                                      ticketIds={[t.id]}
                                      options={partyOptions}
                                      // The route param is a string; the picker keys on
                                      // the numeric master id.
                                      value={Number(customerId)}
                                      valueKind="customer"
                                      disabled={t.is_billed}
                                      disabledReason={t.is_billed
                                        ? "Already billed — delete that billing before moving this ticket."
                                        : undefined}
                                      onDone={afterRetag}
                                      onError={setTicketsError}
                                    />
                                  </div>
                                </div>
                              </td>

                              {/* WHO PAYS. Flipping this moves the ticket to the other
                                  billing screen, which is the whole point — a ticket
                                  belongs to exactly one payer. */}
                              <td className="px-3 py-2 whitespace-nowrap">
                                <div className="min-w-40">
                                  <RetagPayerControl
                                    ticketId={t.id}
                                    customerId={t.customer_id ?? null}
                                    corporateId={t.corporate_id ?? null}
                                    employerOf={employerOf}
                                    disabled={t.is_billed}
                                    disabledReason={t.is_billed
                                      ? "Already billed — delete that billing before moving this ticket."
                                      : undefined}
                                    onDone={afterRetag}
                                    onError={setTicketsError}
                                  />
                                </div>
                              </td>
                              {INCENTIVE_TYPE_COLS.map((col) => {
                                const val = t.incentive_breakdown?.[col.key] ?? null;
                                return (
                                  <td key={col.key} className="px-3 py-2 text-[11px] text-right font-mono whitespace-nowrap border-l border-gray-100">
                                    {val != null ? (
                                      <span className="text-amber-600 font-semibold">₹{val.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                                    ) : (
                                      <span className="text-gray-300">—</span>
                                    )}
                                  </td>
                                );
                              })}
                              <td className="px-3 py-2 text-[11px] text-right font-mono whitespace-nowrap border-l-2 border-gray-200">
                                {totalInc > 0 ? (
                                  <span className="text-emerald-700 font-bold">₹{totalInc.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
                                ) : (
                                  <span className="text-gray-300">—</span>
                                )}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      ) : (
        /* Billing Info tab */
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-700">Saved billings</p>
            <button
              onClick={fetchBillings}
              disabled={loadingBillings}
              className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-2.5 py-1.5 rounded-lg text-[11px] font-medium hover:bg-gray-50 disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingBillings ? "animate-spin" : ""}`} /> Refresh
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  {["BILLING STATEMENT", "PERIOD", "TICKETS", "TOTAL FARE", "TOTAL MARKUP", "TOTAL GST", "GRAND TOTAL", "CREATED", "ACTIONS"].map((h) => (
                    <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loadingBillings ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-12 text-center text-xs text-gray-400">
                      <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading billings…
                    </td>
                  </tr>
                ) : billings.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-16 text-center">
                      <div className="flex flex-col items-center justify-center">
                        <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                          <FileText className="w-7 h-7 text-gray-300" />
                        </div>
                        <p className="text-sm font-medium text-gray-600">No billings yet</p>
                        <p className="text-xs text-gray-400 mt-1">Create one from the Sold Tickets tab.</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  billings.map((b, idx) => (
                    <tr key={b.id} className={`border-b border-gray-50 hover:bg-blue-50/30 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                      <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{b.billing_name}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-500">{b.period_from} → {b.period_to}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-600">{b.item_count}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-600">{money(b.total_base)}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-600">{money(b.total_markup + b.total_additional_markup)}</td>
                      <td className="px-3 py-2 text-[11px] text-amber-600">{money(b.total_gst)}</td>
                      <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{money(b.grand_total)}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-500">{new Date(b.created_at).toLocaleDateString()}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => openView(b)}
                            disabled={loadingViewId === b.id}
                            className="flex items-center gap-1 px-2.5 py-1 bg-white border border-gray-200 text-gray-700 rounded-lg text-[10px] font-semibold hover:bg-gray-50 disabled:opacity-50"
                          >
                            <Eye className="w-3 h-3" /> {loadingViewId === b.id ? "…" : "View"}
                          </button>
                          <button
                            onClick={() => openEdit(b)}
                            disabled={loadingEditId === b.id}
                            className="flex items-center gap-1 px-2.5 py-1 bg-white border border-gray-200 text-gray-700 rounded-lg text-[10px] font-semibold hover:bg-gray-50 disabled:opacity-50"
                          >
                            <Edit2 className="w-3 h-3" /> {loadingEditId === b.id ? "…" : "Edit"}
                          </button>
                          <button
                            onClick={() => downloadPdf(b.id)}
                            disabled={downloadingId === b.id}
                            className="flex items-center gap-1 px-2.5 py-1 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg text-[10px] font-semibold disabled:opacity-50"
                          >
                            <Download className="w-3 h-3" /> {downloadingId === b.id ? "…" : "PDF"}
                          </button>
                          <button onClick={() => deleteBilling(b)} className="p-1.5 hover:bg-red-50 rounded-lg" title="Delete">
                            <Trash2 className="w-3.5 h-3.5 text-red-400" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}


      {/* Save Billing modal */}
      {showSaveBilling && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center">
                  <Save className="w-4 h-4 text-emerald-600" />
                </div>
                <h2 className="text-sm font-bold text-gray-900">Save Billing</h2>
              </div>
              <button onClick={() => setShowSaveBilling(false)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>
            <div className="px-6 py-4 space-y-3">
              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Billing Name *</label>
                <input
                  value={billingName}
                  onChange={(e) => setBillingName(e.target.value)}
                  placeholder="e.g. June 2026 — Acme"
                  autoFocus
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
                />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Billing Period *
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="date"
                    value={periodFrom}
                    onChange={(e) => setPeriodFrom(e.target.value)}
                    className="flex-1 min-w-0 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
                  />
                  <span className="text-gray-400 text-sm">→</span>
                  <input
                    type="date"
                    value={periodTo}
                    onChange={(e) => setPeriodTo(e.target.value)}
                    className="flex-1 min-w-0 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
                  />
                </div>
                <p className="text-[10px] text-gray-400 mt-1">
                  {dateFrom && dateTo
                    ? "From the date range you applied."
                    : "Taken from the first and last issue date of the tickets you selected. It prints on the invoice — adjust it if this bill covers a different period."}
                  {periodUndated > 0 && ` ${periodUndated} selected ${periodUndated === 1 ? "ticket has" : "tickets have"} no readable date and were ignored here.`}
                </p>
                {!periodFrom && !periodTo && (
                  <p className="text-[10px] text-amber-600 mt-1">
                    None of the selected tickets has a readable date — set the period this bill covers.
                  </p>
                )}
                {periodFrom && periodTo && periodFrom > periodTo && (
                  <p className="text-[10px] text-red-500 mt-1">The From date must not be after the To date.</p>
                )}
              </div>
              <div className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2.5 text-[11px] text-gray-600 space-y-1">
                <div className="flex justify-between"><span>Selected Tickets</span><span className="font-semibold">{selectedSummary.count}</span></div>
                <div className="flex justify-between"><span>Grand Total</span><span className="font-semibold">{money(selectedSummary.total)}</span></div>
              </div>
            </div>
            <div className="px-6 pb-5 flex gap-3">
              <button onClick={() => setShowSaveBilling(false)} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
              <button
                onClick={saveBilling}
                disabled={
                  savingBilling || !billingName.trim()
                  || !periodFrom || !periodTo || periodFrom > periodTo
                }
                className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
              >
                {savingBilling ? "Saving…" : "Save Billing"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* View Billing modal */}
      {viewBilling && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
                  <FileText className="w-4 h-4 text-[#1e3a5f]" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-gray-900">{viewBilling.billing_name}</h2>
                  <p className="text-[10px] text-gray-400">
                    {viewBilling.period_from} → {viewBilling.period_to}
                    {viewBilling.billing_type ? ` · ${viewBilling.billing_type}` : ""} · {viewBilling.line_items.length} tickets
                  </p>
                </div>
              </div>
              <button onClick={() => setViewBilling(null)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>

            <div className="overflow-auto">
              <table className="w-full">
                <thead className="sticky top-0">
                  <tr style={{ background: "#1e3a5f" }}>
                    {["TICKET #", "AIRLINE", "CODE", "PASSENGER", "SECTOR", "DATE", "TOTAL FARE", "MARKUP", "ADD. MARKUP", "CGST", "SGST", "IGST", "TOTAL BILLING"].map((h) => (
                      <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {viewBilling.line_items.map((it, idx) => (
                    <tr key={`${it.ticket_id}-${idx}`} className={`border-b border-gray-50 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                      <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{it.ticket_number ?? "—"}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-600">{it.airline_name ?? "—"}</td>
                      <td className="px-3 py-2 text-[11px] font-mono text-gray-600">{it.airlines_code ?? "—"}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-600">{it.passenger ?? "—"}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-500">{it.sector ?? "—"}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-500">{it.ticket_date ?? "—"}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-600">{money(it.base_amount)}</td>
                      <td className="px-3 py-2 text-[11px] font-semibold text-emerald-600">{money(it.markup_amount)}</td>
                      <td className="px-3 py-2 text-[11px] text-gray-600">{money(it.additional_markup)}</td>
                      {/* The heads as SAVED on the bill, not recomputed — an issued
                          invoice shows what was issued. */}
                      <GstCells split={{
                        cgst: it.cgst, sgst: it.sgst, igst: it.igst,
                        gst: it.gst_amount, treatment: viewBilling.gst_treatment ?? "unsplit",
                      }} />
                      <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{money(it.total)}</td>
                    </tr>
                  ))}
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-3 py-2 text-[11px] text-gray-700" colSpan={6}>Total ({viewBilling.line_items.length})</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{money(viewBilling.total_base)}</td>
                    <td className="px-3 py-2 text-[11px] text-emerald-700">{money(viewBilling.total_markup)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{money(viewBilling.total_additional_markup)}</td>
                    <GstTotalCells
                      cgst={viewBilling.total_cgst} sgst={viewBilling.total_sgst}
                      igst={viewBilling.total_igst} gst={viewBilling.total_gst}
                      treatment={viewBilling.gst_treatment ?? "unsplit"}
                    />
                    <td className="px-3 py-2 text-[11px] text-gray-900">{money(viewBilling.grand_total)}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="px-6 py-4 border-t border-gray-100 flex gap-3 justify-end">
              <button onClick={() => setViewBilling(null)} className="border border-gray-200 rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">
                Close
              </button>
              <button
                onClick={() => downloadPdf(viewBilling.id)}
                disabled={downloadingId === viewBilling.id}
                className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50"
              >
                <Download className="w-4 h-4" /> {downloadingId === viewBilling.id ? "…" : "Download PDF"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Billing (per-ticket markup) modal */}
      {editBilling && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
                  <Edit2 className="w-4 h-4 text-[#1e3a5f]" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-gray-900">Edit Additional Markup — {editBilling.billing_name}</h2>
                  <p className="text-[10px] text-gray-400">
                    {editBilling.period_from} → {editBilling.period_to}
                    {editBilling.billing_type ? ` · ${editBilling.billing_type}` : ""} · {editBilling.line_items.length} tickets · edit each ticket&apos;s additional markup
                  </p>
                </div>
              </div>
              <button onClick={() => setEditBilling(null)} className="p-1.5 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>

            <div className="overflow-auto">
              <table className="w-full">
                <thead className="sticky top-0">
                  <tr style={{ background: "#1e3a5f" }}>
                    {["TICKET #", "PASSENGER", "SECTOR", "DATE", "TOTAL FARE", "MARKUP", "ADD. MARKUP", "CGST", "SGST", "IGST", "TOTAL BILLING"].map((h) => (
                      <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {editBilling.line_items.map((it, idx) => {
                    const c = editRowCalc(it, addlEdits[it.ticket_id] ?? "", editBilling);
                    return (
                      <tr key={`${it.ticket_id}-${idx}`} className={`border-b border-gray-50 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                        <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{it.ticket_number ?? "—"}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-600">{it.passenger ?? "—"}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{it.sector ?? "—"}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{it.ticket_date ?? "—"}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-600">{money(c.base)}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-600">{money(c.markup)}</td>
                        <td className="px-3 py-2">
                          <input
                            type="number"
                            value={addlEdits[it.ticket_id] ?? ""}
                            onChange={(e) => setAddlEdits((prev) => ({ ...prev, [it.ticket_id]: e.target.value }))}
                            placeholder="0"
                            className="w-24 border border-gray-200 rounded px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-white"
                          />
                        </td>
                        <GstCells split={c.split} />
                        <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{money(c.total)}</td>
                      </tr>
                    );
                  })}
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-3 py-2 text-[11px] text-gray-700" colSpan={4}>Total ({editBilling.line_items.length})</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{money(editTotals.base)}</td>
                    <td className="px-3 py-2 text-[11px] text-emerald-700">{money(editTotals.markup)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{money(editTotals.addl)}</td>
                    <GstTotalCells
                      cgst={editTotals.cgst} sgst={editTotals.sgst} igst={editTotals.igst}
                      gst={editTotals.gst} treatment={editBilling.gst_treatment ?? "unsplit"}
                    />
                    <td className="px-3 py-2 text-[11px] text-gray-900">{money(editTotals.total)}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="px-6 py-4 border-t border-gray-100 flex gap-3 justify-end">
              <button onClick={() => setEditBilling(null)} className="border border-gray-200 rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-50">
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={savingEdit}
                className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50"
              >
                <Save className="w-4 h-4" /> {savingEdit ? "Saving…" : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
