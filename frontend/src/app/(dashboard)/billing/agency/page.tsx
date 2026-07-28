"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Building2, RefreshCw, Ticket, FileText, Download, Trash2, Save, X, Eye, Edit2 } from "lucide-react";
import api from "@/lib/api";
import { INCENTIVE_TYPE_COLS } from "@/lib/incentives";

type AgencyOpt = {
  id: number;
  name: string;
  vendor_type: string | null;
  gst_number: string | null;
  pan_number: string | null;
  contact_email: string | null;
  contact_phone: string | null;
};

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
  base_amount: number;
  markup_amount: number;
  gst_amount: number;
  total_with_markup: number;
};

type AgencyTicketsResponse = {
  agency: AgencyOpt;
  tickets: SoldTicket[];
  summary: { count: number; total_base: number; total_markup: number; total_gst: number; total_with_markup: number };
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
  total: number;
};

type BillingDetail = {
  id: number;
  agency_id: number | null;
  billing_name: string;
  period_from: string;
  period_to: string;
  billing_type: string | null;
  total_base: number;
  total_markup: number;
  total_additional_markup: number;
  total_gst: number;
  grand_total: number;
  line_items: BillingDetailLine[];
  created_at: string;
};

const TABS = ["Tickets", "Billings"] as const;
type Tab = (typeof TABS)[number];

// Agencies have no stored default markup; GST always uses the agency rule (tax on markup only).
const GST_RATE = 0.18;

const money = (n: number | null | undefined) =>
  n == null ? "—" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

function passengerName(t: SoldTicket): string {
  return t.pax_name || [t.first_name, t.last_name].filter(Boolean).join(" ") || "—";
}

/** Recompute one row with the entered additional (flat) markup + discount. Agency GST = 18% on markup. */
function rowCalc(t: SoldTicket, additionalStr: string, discountStr: string) {
  const base = t.base_amount;
  const addl = parseFloat(additionalStr) || 0;
  const disc = parseFloat(discountStr) || 0;
  const totalMarkup = addl;
  // Discount reduces the taxable value first, then GST applies on the reduced amount.
  const gst = Math.max(0, totalMarkup - disc) * GST_RATE;
  const total = base + totalMarkup - disc + gst;
  return { base, addl, disc, totalMarkup, gst, total };
}

/** Recompute a saved billing line when its additional markup is being edited (discount preserved). */
function editRowCalc(it: BillingDetailLine, additionalStr: string) {
  const base = it.base_amount;
  const markup = it.markup_amount; // 0 for agency billings
  const addl = parseFloat(additionalStr) || 0;
  const disc = it.discount ?? 0;
  const totalMarkup = markup + addl;
  const gst = Math.max(0, totalMarkup - disc) * GST_RATE;
  const total = base + totalMarkup - disc + gst;
  return { base, addl, markup, gst, total };
}

export default function AgencyBillingPage() {
  const [agencies, setAgencies] = useState<AgencyOpt[]>([]);
  const [agencyId, setAgencyId] = useState<number | "">("");
  const [tab, setTab] = useState<Tab>("Tickets");
  const selectedAgency = useMemo(() => agencies.find((a) => a.id === agencyId) ?? null, [agencies, agencyId]);

  // Tickets
  const [dateField, setDateField] = useState<"ticket" | "travel">("ticket");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [soldTickets, setSoldTickets] = useState<SoldTicket[] | null>(null);
  const [loadingTickets, setLoadingTickets] = useState(false);
  const [ticketsError, setTicketsError] = useState<string | null>(null);
  const [additional, setAdditional] = useState<Record<number, string>>({});
  const [discounts, setDiscounts] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Save Billing
  const [showSaveBilling, setShowSaveBilling] = useState(false);
  const [billingName, setBillingName] = useState("");
  const [savingBilling, setSavingBilling] = useState(false);

  // Billings
  const [billings, setBillings] = useState<BillingListItem[]>([]);
  const [loadingBillings, setLoadingBillings] = useState(false);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [viewBilling, setViewBilling] = useState<BillingDetail | null>(null);
  const [loadingViewId, setLoadingViewId] = useState<number | null>(null);
  const [editBilling, setEditBilling] = useState<BillingDetail | null>(null);
  const [loadingEditId, setLoadingEditId] = useState<number | null>(null);
  const [addlEdits, setAddlEdits] = useState<Record<number, string>>({});
  const [savingEdit, setSavingEdit] = useState(false);

  useEffect(() => {
    api
      .get<AgencyOpt[]>("/agencies/", { params: { limit: 1000 } })
      .then((r) => setAgencies(r.data))
      .catch(() => {});
  }, []);

  const fetchBillings = useCallback(async () => {
    if (!agencyId) {
      setBillings([]);
      return;
    }
    setLoadingBillings(true);
    try {
      const { data } = await api.get<BillingListItem[]>(`/agency-billings/${agencyId}/billings`);
      setBillings(data);
    } catch {
      /* ignore */
    } finally {
      setLoadingBillings(false);
    }
  }, [agencyId]);

  // When the agency changes, reset the ticket view and load its saved billings.
  useEffect(() => {
    setSoldTickets(null);
    setSelected(new Set());
    setAdditional({});
    setDiscounts({});
    setTicketsError(null);
    fetchBillings();
  }, [agencyId, fetchBillings]);

  const applyRange = useCallback(async () => {
    if (!agencyId) {
      setTicketsError("Select an agency first.");
      return;
    }
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
      const { data } = await api.get<AgencyTicketsResponse>(`/agency-billings/${agencyId}/tickets`, { params });
      setSoldTickets(data.tickets);
      setAdditional({});
      setDiscounts({});
      setSelected(new Set());
    } catch {
      setTicketsError("Failed to load tickets.");
    } finally {
      setLoadingTickets(false);
    }
  }, [agencyId, dateFrom, dateTo, dateField]);

  // Live summary over the loaded tickets + entered additional markups.
  const summary = useMemo(() => {
    const rows = soldTickets ?? [];
    let base = 0,
      addl = 0,
      gst = 0,
      total = 0;
    for (const t of rows) {
      const c = rowCalc(t, additional[t.id] ?? "", discounts[t.id] ?? "");
      base += c.base;
      addl += c.addl;
      gst += c.gst;
      total += c.total;
    }
    return { count: rows.length, base, addl, gst, total };
  }, [soldTickets, additional, discounts]);

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

  const selectedSummary = useMemo(() => {
    const rows = (soldTickets ?? []).filter((t) => selected.has(t.id));
    let total = 0;
    for (const t of rows) total += rowCalc(t, additional[t.id] ?? "", discounts[t.id] ?? "").total;
    return { count: rows.length, total };
  }, [soldTickets, selected, additional, discounts]);

  const editTotals = useMemo(() => {
    const items = editBilling?.line_items ?? [];
    let base = 0,
      addl = 0,
      gst = 0,
      total = 0;
    for (const it of items) {
      const c = editRowCalc(it, addlEdits[it.ticket_id] ?? "");
      base += c.base;
      addl += c.addl;
      gst += c.gst;
      total += c.total;
    }
    return { base, addl, gst, total };
  }, [editBilling, addlEdits]);

  const saveBilling = async () => {
    const rows = (soldTickets ?? []).filter((t) => selected.has(t.id) && !t.is_billed);
    if (!agencyId || !billingName.trim() || rows.length === 0) return;
    if (!dateFrom || !dateTo) {
      alert("Select a From and To date before saving a billing (they define the billing period).");
      return;
    }
    setSavingBilling(true);
    try {
      await api.post(`/agency-billings/${agencyId}/billings`, {
        billing_name: billingName.trim(),
        period_from: dateFrom,
        period_to: dateTo,
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
      applyRange();
      setTab("Billings");
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
      const { data } = await api.get<BillingDetail>(`/agency-billings/${agencyId}/billings/${b.id}`);
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
      const { data } = await api.get<BillingDetail>(`/agency-billings/${agencyId}/billings/${b.id}`);
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
      await api.patch(`/agency-billings/${agencyId}/billings/${editBilling.id}`, {
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
      const res = await api.get(`/agency-billings/${agencyId}/billings/${id}/pdf`, { responseType: "blob" });
      const url = window.URL.createObjectURL(res.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `agency-billing-${id}.pdf`;
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
      await api.delete(`/agency-billings/${agencyId}/billings/${b.id}`);
      fetchBillings();
    } catch {
      alert("Failed to delete billing.");
    }
  };

  const TICKET_COLSPAN = 13 + INCENTIVE_TYPE_COLS.length + 1;

  return (
    <div className="space-y-4">
      {/* Header + agency selector */}
      <div className="flex items-start gap-3">
        <div className="mt-0.5 w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
          <Building2 className="w-5 h-5 text-[#1e3a5f]" />
        </div>
        <div className="flex-1">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Billing</p>
          <h1 className="text-xl font-bold text-gray-900">Agency Billing</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Select an agency from your Customer Directory, review its tickets, and bill them.
          </p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex flex-wrap items-end gap-3">
        <div className="min-w-65">
          <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Agency</label>
          <select
            value={agencyId}
            onChange={(e) => setAgencyId(e.target.value ? Number(e.target.value) : "")}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
          >
            <option value="">— Select agency —</option>
            {agencies.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        {selectedAgency && (
          <div className="text-[11px] text-gray-500 pb-2">
            {selectedAgency.vendor_type && <span className="mr-3">Type: {selectedAgency.vendor_type}</span>}
            {selectedAgency.gst_number && <span className="mr-3">GST: {selectedAgency.gst_number}</span>}
            {selectedAgency.contact_email && <span>{selectedAgency.contact_email}</span>}
          </div>
        )}
      </div>

      {!agencyId ? (
        <div className="flex flex-col items-center justify-center py-24 bg-white rounded-xl border border-gray-100 text-center">
          <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
            <Building2 className="w-7 h-7 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">Select an agency to begin</p>
          <p className="text-xs text-gray-400 mt-1">Its tickets and saved billings will appear here.</p>
        </div>
      ) : (
        <>
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
                  {t === "Tickets" ? <Ticket className="w-3.5 h-3.5" /> : <FileText className="w-3.5 h-3.5" />}
                  {t}
                  {t === "Billings" && billings.length > 0 && (
                    <span className="ml-1 bg-gray-100 text-gray-600 text-[9px] font-bold px-1.5 py-0.5 rounded-full">{billings.length}</span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {tab === "Tickets" ? (
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
                  onClick={applyRange}
                  disabled={loadingTickets}
                  className="bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50"
                >
                  {loadingTickets ? "Loading…" : "Apply"}
                </button>
                <span className="text-[10px] text-gray-400 pb-2">Dates optional — leave blank to show all of the agency&apos;s tickets.</span>
                {soldTickets && soldTickets.length > 0 && (
                  <button
                    onClick={() => setShowSaveBilling(true)}
                    disabled={selected.size === 0}
                    className="ml-auto flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Save className="w-4 h-4" /> Save Billing{selected.size > 0 ? ` (${selected.size})` : ""}
                  </button>
                )}
              </div>

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
                  <p className="text-sm font-medium text-gray-600">Click Apply to view this agency&apos;s tickets</p>
                  <p className="text-xs text-gray-400 mt-1">Optionally pick a From / To date to filter first.</p>
                </div>
              ) : (
                <>
                  {/* Summary cards */}
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {[
                      { label: "Tickets", value: String(summary.count) },
                      { label: "Total Base", value: money(summary.base) },
                      { label: "Total Markup", value: money(summary.addl) },
                      { label: "Total GST (18%)", value: money(summary.gst) },
                      { label: "Grand Total", value: money(summary.total) },
                    ].map((s) => (
                      <div key={s.label} className="bg-white rounded-xl border border-gray-100 px-4 py-3 shadow-sm">
                        <p className="text-sm font-bold text-gray-900 leading-none">{s.value}</p>
                        <p className="text-[11px] text-gray-400 mt-1">{s.label}</p>
                      </div>
                    ))}
                  </div>

                  <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                    <div className="px-4 py-3 border-b border-gray-100">
                      <p className="text-xs font-semibold text-gray-700">
                        Tickets tagged to {selectedAgency?.name}
                        {dateFrom || dateTo ? ` · ${dateField === "travel" ? "travel" : "issue"} date ${dateFrom || "…"} → ${dateTo || "…"}` : ""}
                      </p>
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        Agency billing — 18% GST on markup only. Enter Additional Markup / Discount per ticket to recalculate.
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
                            {["TICKET #", "AIRLINE", "CODE", "PASSENGER", "SECTOR", "DATE", "TOTAL FARE", "ADD. MARKUP", "DISCOUNT", "GST", "TOTAL BILLING", "STATUS"].map((h) => (
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
                              <td colSpan={TICKET_COLSPAN} className="px-4 py-16 text-center">
                                <div className="flex flex-col items-center justify-center">
                                  <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                                    <Ticket className="w-7 h-7 text-gray-300" />
                                  </div>
                                  <p className="text-sm font-medium text-gray-600">No tickets for this agency</p>
                                  <p className="text-xs text-gray-400 mt-1">No tickets are tagged to {selectedAgency?.name}{dateFrom || dateTo ? " in this date range" : ""}.</p>
                                </div>
                              </td>
                            </tr>
                          ) : (
                            soldTickets.map((t, idx) => {
                              const c = rowCalc(t, additional[t.id] ?? "", discounts[t.id] ?? "");
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
                                  <td className="px-3 py-2">
                                    <input
                                      type="number"
                                      step="any"
                                      value={additional[t.id] ?? ""}
                                      disabled={t.is_billed}
                                      onChange={(e) => setAdditional((prev) => ({ ...prev, [t.id]: e.target.value }))}
                                      placeholder="0"
                                      className="w-24 border border-gray-200 rounded px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-white disabled:bg-gray-50 disabled:text-gray-400"
                                    />
                                  </td>
                                  <td className="px-3 py-2">
                                    <input
                                      type="number"
                                      step="any"
                                      value={discounts[t.id] ?? ""}
                                      disabled={t.is_billed}
                                      onChange={(e) => setDiscounts((prev) => ({ ...prev, [t.id]: e.target.value }))}
                                      placeholder="0"
                                      className="w-24 border border-gray-200 rounded px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-rose-400/50 bg-white disabled:bg-gray-50 disabled:text-gray-400"
                                    />
                                  </td>
                                  <td className="px-3 py-2 text-[11px] text-amber-600">{money(c.gst)}</td>
                                  <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{money(c.total)}</td>
                                  <td className="px-3 py-2 whitespace-nowrap">
                                    {t.is_billed ? (
                                      <span className="inline-block bg-emerald-50 text-emerald-700 text-[10px] font-semibold px-2 py-0.5 rounded-full border border-emerald-200">Billed</span>
                                    ) : (
                                      <span className="inline-block bg-gray-100 text-gray-500 text-[10px] font-semibold px-2 py-0.5 rounded-full">Not Billed</span>
                                    )}
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
            /* Billings tab */
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
                            <p className="text-xs text-gray-400 mt-1">Create one from the Tickets tab.</p>
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
        </>
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
                  placeholder="e.g. June 2026 — Agency"
                  autoFocus
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30 bg-gray-50"
                />
              </div>
              <div className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2.5 text-[11px] text-gray-600 space-y-1">
                <div className="flex justify-between"><span>Agency</span><span className="font-semibold">{selectedAgency?.name}</span></div>
                <div className="flex justify-between"><span>Period</span><span className="font-semibold">{dateFrom || "—"} → {dateTo || "—"}</span></div>
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
                disabled={savingBilling || !billingName.trim()}
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
                    {viewBilling.period_from} → {viewBilling.period_to} · {viewBilling.line_items.length} tickets
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
                    {["TICKET #", "AIRLINE", "CODE", "PASSENGER", "SECTOR", "DATE", "TOTAL FARE", "ADD. MARKUP", "GST", "TOTAL BILLING"].map((h) => (
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
                      <td className="px-3 py-2 text-[11px] text-gray-600">{money(it.additional_markup)}</td>
                      <td className="px-3 py-2 text-[11px] text-amber-600">{money(it.gst_amount)}</td>
                      <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{money(it.total)}</td>
                    </tr>
                  ))}
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-3 py-2 text-[11px] text-gray-700" colSpan={6}>Total ({viewBilling.line_items.length})</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{money(viewBilling.total_base)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{money(viewBilling.total_additional_markup)}</td>
                    <td className="px-3 py-2 text-[11px] text-amber-700">{money(viewBilling.total_gst)}</td>
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

      {/* Edit Billing (per-ticket additional markup) modal */}
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
                    {editBilling.period_from} → {editBilling.period_to} · {editBilling.line_items.length} tickets · edit each ticket&apos;s additional markup
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
                    {["TICKET #", "PASSENGER", "SECTOR", "DATE", "TOTAL FARE", "ADD. MARKUP", "GST", "TOTAL BILLING"].map((h) => (
                      <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {editBilling.line_items.map((it, idx) => {
                    const c = editRowCalc(it, addlEdits[it.ticket_id] ?? "");
                    return (
                      <tr key={`${it.ticket_id}-${idx}`} className={`border-b border-gray-50 ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>
                        <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{it.ticket_number ?? "—"}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-600">{it.passenger ?? "—"}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{it.sector ?? "—"}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-500">{it.ticket_date ?? "—"}</td>
                        <td className="px-3 py-2 text-[11px] text-gray-600">{money(c.base)}</td>
                        <td className="px-3 py-2">
                          <input
                            type="number"
                            value={addlEdits[it.ticket_id] ?? ""}
                            onChange={(e) => setAddlEdits((prev) => ({ ...prev, [it.ticket_id]: e.target.value }))}
                            placeholder="0"
                            className="w-24 border border-gray-200 rounded px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40 bg-white"
                          />
                        </td>
                        <td className="px-3 py-2 text-[11px] text-amber-600">{money(c.gst)}</td>
                        <td className="px-3 py-2 text-[11px] font-semibold text-gray-800">{money(c.total)}</td>
                      </tr>
                    );
                  })}
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-3 py-2 text-[11px] text-gray-700" colSpan={4}>Total ({editBilling.line_items.length})</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{money(editTotals.base)}</td>
                    <td className="px-3 py-2 text-[11px] text-gray-800">{money(editTotals.addl)}</td>
                    <td className="px-3 py-2 text-[11px] text-amber-700">{money(editTotals.gst)}</td>
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
