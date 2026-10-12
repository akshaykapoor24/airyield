"use client";

// Agency manager (table + add/edit modal + bulk add + xlsx upload) for
// User master → Agency Master. Agencies are private to the user; details are
// copied from the global master at add-time.
//
// ONE ROW IS ONE BRANCH ON ONE CHANNEL. A vendor exists as several master rows,
// one per branch ("Air India Limited" is 3, "Riya Travel & Tours" is 14), and
// Lords Delhi and Lords Mumbai are separate commercial relationships with
// separate deposits, limits and invoices. So the picker is two steps — agency,
// then branch — and both always show. The word "Supplier" is deliberately absent
// from everything the user reads here: to them these are agencies, and the master
// they come from is an implementation detail.
//
// TERMS ARE PER CHANNEL and mandatory. An agency is routinely cash on GDS (it
// books on our IATA stock, so we carry the BSP liability and it pays first) and
// credit on LCC (each airline settles through its own wallet, so exposure is
// capped). THERE IS NO "BOTH" CARD: an agency that works both channels is added
// twice, once per channel, so each gets its own terms block, its own deposit, its
// own balance and its own line in the table. The old single row carrying two
// arrangements had to be special-cased by every screen that read it.
//
// THE TAX BLOCK IS ORDERED BY WHAT CAN BE CHECKED. State fixes a GSTIN's first
// two characters and PAN fixes characters 3 to 12, so the form asks for state,
// then PAN, then whether the agency is registered at all, and only then offers
// the GSTIN box — by which point three of the four checks in lib/indiaTax have
// something to compare against. State is required for exactly that reason.

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle, ArrowRight, Check, Clock, Edit2, Filter, PencilLine,
  Plus, ReceiptIndianRupee, RefreshCw, Search, Trash2, Wallet, X,
} from "lucide-react";
import api from "@/lib/api";
import SearchSelect from "@/components/ui/SearchSelect";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import {
  STATE_NAMES, canonicalState, gstinError, gstinPlaceholder, gstinTypingError,
  normaliseTaxId, panError, panTypingError,
} from "@/lib/indiaTax";
import {
  INPUT, LABEL, apiError,
  ActiveBadge, UploadBox, ModalShell,
} from "@/components/userMaster/shared";

export type Channel = "GDS" | "LCC";
// What a row may SAY it trades on. "BOTH" is read-only: rows created before
// agencies were split per channel still carry it, and the account page can still
// widen one, so every reader has to handle it — but nothing here creates it.
export type ChannelScope = Channel | "BOTH";

/** One channel's current arrangement, as the API returns it. */
export type AgencyTerms = {
  channel: Channel;
  agency_type: "cash" | "credit";
  billing_cycle: string;
  credit_limit: number | null;
  usage_percent: number | null;
  terms_id: number;
  effective_from: string;
  cycle_anchor_date: string;
  deposit_paid: number;
};

export type AgencyRow = {
  id: number;
  name: string;
  supplier_id: number | null;
  branch_code: string;
  branch_name: string | null;
  channels: ChannelScope;
  address: string | null;
  state: string | null;
  city: string | null;
  region_chapter: string | null;
  // Stored rather than inferred from a non-null gst_number: "not registered" and
  // "nobody has filled it in yet" are different facts, and only the first one
  // means the blank cell is correct.
  gst_registered: boolean;
  gst_number: string | null;
  pan_number: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  notes: string | null;
  // OUR identifier, issued by the system (AG-0001 …) unless typed in. Shared by a
  // branch's GDS and LCC rows, unique otherwise. Null only on rows nobody has saved since.
  agency_code: string | null;
  // The user's own references — optional, not unique (a branch's GDS and LCC rows
  // usually share them). customer_code is stored uppercased; account_code as typed.
  customer_code: string | null;
  account_code: string | null;
  // The two service rates, one per direction — see SERVICE_FEE_DIRECTIONS. Null
  // means nobody has been asked; a stored 0 means "we deliberately charge nothing",
  // so the two must not be collapsed into one falsy check.
  vendor_service_charge_type: ServiceFeeType | null;
  vendor_service_charge_value: number | null;
  vendor_service_charge_gst: GstTreatment | null;
  customer_service_fee_type: ServiceFeeType | null;
  customer_service_fee_value: number | null;
  customer_service_fee_gst: GstTreatment | null;
  is_active: boolean;
  terms: AgencyTerms[];
  // Where this agency stands with the shared supplier master. `supplier_id` set
  // means it is in there; otherwise a request may be waiting on the platform
  // admin, or have been rejected, or never have been filed (an agency typed in
  // before this existed, or uploaded from a sheet).
  supplier_request_id: number | null;
  supplier_request_status: "pending" | "approved" | "rejected" | null;
  supplier_request_reason: string | null;
};

/** What the MASTER column shows for a row, and why. */
export function masterState(a: AgencyRow) {
  if (a.supplier_id) return "in_master" as const;
  if (a.supplier_request_status === "pending") return "pending" as const;
  if (a.supplier_request_status === "rejected") return "rejected" as const;
  return "unlisted" as const;
}

// The master fields an agency copies from at add-time. Note phone/email come
// from the DIRECTORY columns: contact_phone / contact_email are empty across the
// whole master, so reading only those filled nothing.
type SupplierFull = {
  id: number;
  code: string | null;
  name: string;
  branch: string | null;
  address_1: string | null;
  address_2: string | null;
  address_3: string | null;
  city: string | null;
  region_chapter: string | null;
  gst_number: string | null;
  pan_number: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  telephone_mobile: string | null;
  email_address: string | null;
  alternate_email_id: string | null;
  notes: string | null;
};

// No "Both". An agency working both channels is added twice — see the note at the
// top of this file — which is what gives each channel its own terms and balance.
const CHANNEL_CHOICES: { value: Channel; label: string; hint: string }[] = [
  { value: "GDS", label: "GDS", hint: "Books on your IATA stock via a mirror office" },
  { value: "LCC", label: "LCC", hint: "Books on each airline's own agent portal" },
];

// Words that describe the trade rather than name the company. Nearly every row in
// the master carries one, so matching on them tells you nothing — see nearMatches.
const GENERIC_NAME_WORDS = new Set([
  "travel", "travels", "travelling", "tour", "tours", "tourism", "trip", "trips",
  "holiday", "holidays", "vacation", "vacations", "air", "airways", "aviation",
  "world", "global", "international", "india", "indian", "services", "service",
  "solutions", "enterprises", "agency", "agencies", "company", "consultants",
  "pvt", "private", "ltd", "limited", "llp", "inc", "corp", "and", "the", "for",
]);

const AGENCY_TYPES = [
  { value: "cash", label: "Cash" },
  { value: "credit", label: "Credit" },
] as const;

const BILLING_CYCLES = [
  { value: "weekly", label: "Weekly" },
  { value: "fortnightly", label: "Fortnightly" },
  { value: "monthly", label: "Monthly" },
] as const;

// ── Service charge / service fee ──────────────────────────────────────────────
//
// TWO DIRECTIONS, BECAUSE THIS AGENCY IS BOTH A VENDOR AND A CUSTOMER. The same
// row is reached from Vendors data (we buy from them — what they charge is a COST)
// and from Customer data (we sell to them — what we charge is INCOME). The rate we
// pay Lords is not the rate we charge Lords, so the form asks twice and the two are
// stored in separate columns. See backend services/service_fee.py.
export type ServiceFeeType = "percentage" | "fixed";
export type GstTreatment = "inclusive" | "exclusive";

const SERVICE_FEE_TYPES = [
  { value: "percentage", label: "Percentage" },
  { value: "fixed", label: "Fixed" },
] as const;

// EXCLUSIVE IS FIRST AND IS THE DEFAULT. On a ₹1,000 fee the two differ by ₹180 —
// exclusive is ₹1,000 of service with ₹180 of tax on top, inclusive is ₹847.46 of
// service with ₹152.54 already inside — so the question has to be asked rather than
// guessed, and the safe guess when it is skipped is that tax is added.
const GST_TREATMENTS = [
  { value: "exclusive", label: "Exclusive — GST added on top" },
  { value: "inclusive", label: "Inclusive — GST already included" },
] as const;

/** The two directions, in the order the form asks them. `prefix` is the column stem
 *  shared by the API, so a field name is never spelt out twice. */
const SERVICE_FEE_DIRECTIONS = [
  {
    prefix: "vendor_service_charge",
    heading: "As vendor — they charge us",
    label: "Service Charge",
    hint: "What this agency adds when WE BUY from them. A cost to us — read on the Vendors data screens.",
  },
  {
    prefix: "customer_service_fee",
    heading: "As customer — we charge them",
    label: "Service Fee",
    hint: "What WE add when we sell to them. Income to us — read on the Customer data screens.",
  },
] as const;

/** "2% · GST extra" / "₹250 · incl. GST" — one direction in a cell. Mirrors the
 *  backend's service_fee.describe so a list and an export read identically. */
export function serviceFeeLabel(
  type: string | null, value: number | null, gst: string | null,
): string {
  if (!type || value == null) return "";
  const shown = type === "percentage" ? `${value}%` : `₹${value}`;
  return `${shown} · ${gst === "inclusive" ? "incl. GST" : "GST extra"}`;
}

/** Which single channels a declared scope needs terms for. Still handles "BOTH",
 *  because rows created before the split carry it even though nothing makes one. */
const channelsOf = (scope: ChannelScope): Channel[] =>
  scope === "BOTH" ? ["GDS", "LCC"] : [scope];

function money(v: number | null): string {
  if (v == null) return "—";
  return `₹${Number(v).toLocaleString("en-IN")}`;
}

function titleCase(v: string | null): string {
  if (!v) return "—";
  return v.charAt(0).toUpperCase() + v.slice(1);
}

/** "Cash · ₹1,00,00,000 · Monthly" — the whole arrangement in one cell. */
function TermsCell({ t }: { t: AgencyTerms | undefined }) {
  if (!t) return <span className="text-[11px] text-gray-300">—</span>;
  // On cash the usable limit IS the money on deposit, which lives in the ledger.
  const limit = t.agency_type === "cash" ? t.deposit_paid : t.credit_limit;
  return (
    <div className="flex flex-col gap-0.5">
      <span className={`inline-flex w-fit items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
        t.agency_type === "cash"
          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
          : "bg-amber-50 text-amber-700 border-amber-200"
      }`}>{titleCase(t.agency_type)}</span>
      <span className="text-[11px] font-semibold text-gray-700 whitespace-nowrap">
        {money(limit)}
        {t.agency_type === "cash" && t.usage_percent != null && (
          <span className="text-[10px] font-normal text-gray-400"> · {t.usage_percent}%</span>
        )}
      </span>
      <span className="text-[10px] text-gray-400">{titleCase(t.billing_cycle)}</span>
    </div>
  );
}

/** Both directions in one cell, stacked and labelled BUY / SELL.
 *
 *  ONE COLUMN, TWO LINES, rather than two columns: the table is already wide, and
 *  the pair is only meaningful read together — "2%" on its own does not say who is
 *  charging whom, which is the exact confusion these two columns exist to prevent.
 *  The labels are the direction, not the field name, because that is what a reader
 *  scanning the list actually needs to know. */
function ServiceRatesCell({ r }: { r: AgencyRow }) {
  const buy = serviceFeeLabel(r.vendor_service_charge_type, r.vendor_service_charge_value, r.vendor_service_charge_gst);
  const sell = serviceFeeLabel(r.customer_service_fee_type, r.customer_service_fee_value, r.customer_service_fee_gst);
  if (!buy && !sell) return <span className="text-[11px] text-gray-300">—</span>;
  return (
    <div className="flex flex-col gap-0.5 whitespace-nowrap">
      {buy && (
        <span className="text-[10px] text-gray-600">
          <span className="font-bold text-rose-600">BUY</span> {buy}
        </span>
      )}
      {sell && (
        <span className="text-[10px] text-gray-600">
          <span className="font-bold text-emerald-600">SELL</span> {sell}
        </span>
      )}
    </div>
  );
}

function ChannelPills({ scope }: { scope: ChannelScope }) {
  return (
    <div className="flex gap-1">
      {channelsOf(scope).map(c => (
        <span key={c} className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${
          c === "GDS"
            ? "bg-sky-50 text-sky-700 border-sky-200"
            : "bg-violet-50 text-violet-700 border-violet-200"
        }`}>{c}</span>
      ))}
    </div>
  );
}

/** A compact "All …" dropdown for the filter row. Highlighted while it filters. */
function FilterSelect({
  value, onChange, label, options,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  options: [string, string][];
}) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      className={`text-[11px] rounded-lg border px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-sky-400 ${
        value ? "border-sky-300 bg-sky-50 text-sky-800 font-semibold" : "border-gray-200 bg-white text-gray-600"
      }`}>
      <option value="">{label}</option>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

export default function AgencyInfoSection({
  onChange, onGoTo,
}: {
  onChange?: (count: number) => void;
  /** Jump to the Entities / Login IDs tab with this agency preselected. */
  onGoTo?: (tab: "entities" | "logins", agencyId: number) => void;
}) {
  const router = useRouter();
  const [rows, setRows] = useState<AgencyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiErr, setApiErr] = useState("");
  const [modal, setModal] = useState<AgencyRow | null | false>(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setApiErr("");
    try {
      const { data } = await api.get<AgencyRow[]>("/agencies/");
      setRows(data);
      onChange?.(data.length);
    } catch (e) { setApiErr(apiError(e)); }
    finally { setLoading(false); }
  }, [onChange]);

  useEffect(() => { const t = setTimeout(fetchRows, 250); return () => clearTimeout(t); }, [fetchRows]);

  const toggle = async (row: AgencyRow) => {
    try {
      const { data } = await api.patch<AgencyRow>(`/agencies/${row.id}`, { is_active: !row.is_active });
      setRows(p => p.map(r => r.id === row.id ? data : r));
    } catch { alert("Update failed."); }
  };

  // The row awaiting the delete popup. The request runs inside ConfirmDialog, which
  // stays open with the error shown if it fails, rather than closing and alerting.
  const [pendingDelete, setPendingDelete] = useState<AgencyRow | null>(null);
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    await api.delete(`/agencies/${id}`);
    setRows(p => { const next = p.filter(r => r.id !== id); onChange?.(next.length); return next; });
  };

  // Ask the platform admin to add this agency's vendor to the shared master.
  // Used both for a first request (an agency typed in before this existed, or
  // uploaded from a sheet) and to resubmit after a rejection.
  const [requesting, setRequesting] = useState<number | null>(null);
  const requestMaster = async (row: AgencyRow) => {
    setRequesting(row.id);
    try {
      const { data } = await api.post<AgencyRow>(`/agencies/${row.id}/master-request`);
      setRows(p => p.map(r => (r.id === row.id ? data : r)));
    } catch (e) { alert(apiError(e)); }
    finally { setRequesting(null); }
  };

  // Client-side filters over the loaded list — a user's book is hundreds of rows at
  // most. The first is a pick from the agencies already onboarded rather than free
  // text: labelled code · name — branch · channel, because one vendor is several
  // rows (per branch, per channel) and a bare name would not say which.
  const agencyLabel = (r: AgencyRow) =>
    `${r.agency_code ? `${r.agency_code} · ` : ""}${r.name} — ${r.branch_name || r.city || r.branch_code} · ${r.channels}`;
  const agencyOptions = useMemo(() => rows.map(agencyLabel), [rows]);
  const [fAgency, setFAgency] = useState("");
  const [fChannel, setFChannel] = useState<"" | Channel>("");
  const [fTerms, setFTerms] = useState<"" | "cash" | "credit">("");
  const [fMaster, setFMaster] = useState<"" | ReturnType<typeof masterState>>("");
  const [fStatus, setFStatus] = useState<"" | "active" | "inactive">("");
  const filtersOn = !!(fAgency || fChannel || fTerms || fMaster || fStatus);
  const clearFilters = () => { setFAgency(""); setFChannel(""); setFTerms(""); setFMaster(""); setFStatus(""); };

  const visible = useMemo(() => rows.filter(r => {
    if (fAgency && agencyLabel(r) !== fAgency) return false;
    if (fChannel && !channelsOf(r.channels).includes(fChannel)) return false;
    if (fTerms && !r.terms.some(t => t.agency_type === fTerms)) return false;
    if (fMaster && masterState(r) !== fMaster) return false;
    if (fStatus && r.is_active !== (fStatus === "active")) return false;
    return true;
  }), [rows, fAgency, fChannel, fTerms, fMaster, fStatus]);

  const COLUMNS = ["Agency", "Branch", "Channel", "Terms", "Service rates", "GST / PAN", "Contact", "Master", "Status", ""];

  return (
    <div className="space-y-3">
      {/* One row: pick an agency, narrow by the rest, then count / refresh / add. */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="w-72">
          <SearchSelect value={fAgency} options={agencyOptions} onChange={setFAgency}
            placeholder="All onboarded agencies" />
        </div>
        <Filter className="w-3.5 h-3.5 text-gray-400" />
        <FilterSelect value={fChannel} onChange={v => setFChannel(v as "" | Channel)} label="All channels"
          options={[["GDS", "GDS"], ["LCC", "LCC"]]} />
        <FilterSelect value={fTerms} onChange={v => setFTerms(v as "" | "cash" | "credit")} label="All terms"
          options={[["cash", "Cash"], ["credit", "Credit"]]} />
        <FilterSelect value={fMaster} onChange={v => setFMaster(v as "" | ReturnType<typeof masterState>)} label="Any master status"
          options={[["in_master", "In master"], ["pending", "Awaiting approval"], ["rejected", "Rejected"], ["unlisted", "Not requested"]]} />
        <FilterSelect value={fStatus} onChange={v => setFStatus(v as "" | "active" | "inactive")} label="Active & inactive"
          options={[["active", "Active"], ["inactive", "Inactive"]]} />
        {filtersOn && (
          <button onClick={clearFilters} className="flex items-center gap-1 text-[11px] font-semibold text-sky-600 hover:underline">
            <X className="w-3 h-3" /> Clear
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[11px] text-gray-400">
            {filtersOn ? `${visible.length} of ${rows.length}` : rows.length} record{rows.length !== 1 ? "s" : ""}
          </span>
          <button onClick={fetchRows} disabled={loading} title="Refresh"
            className="flex items-center bg-white border border-gray-200 text-gray-600 px-2.5 py-2 rounded-lg hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
          <button onClick={() => setModal(null)}
            className="flex items-center gap-1.5 text-white px-3.5 py-2 rounded-lg text-xs font-medium" style={{ background: "#1e3a5f" }}>
            <Plus className="w-3.5 h-3.5" /> Add Agency
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e4d8c" }}>
                {COLUMNS.map((h, i) => (
                  <th key={i} className={`px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap ${
                    i === COLUMNS.length - 1 ? "sticky right-0" : ""
                  }`} style={i === COLUMNS.length - 1 ? { background: "#1e4d8c" } : undefined}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-xs text-gray-400"><RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />Loading…</td></tr>
              ) : apiErr ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-xs text-red-400">{apiErr}</td></tr>
              ) : visible.length === 0 ? (
                <tr><td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-xs text-gray-400">
                  {rows.length === 0 ? "No agencies yet. Add one, or upload an XLS." : "No agencies match these filters."}
                </td></tr>
              ) : visible.map(r => {
                const byChannel = Object.fromEntries(r.terms.map(t => [t.channel, t]));
                const scope = channelsOf(r.channels);
                return (
                  <tr key={r.id} className={`group border-b border-gray-100 last:border-0 hover:bg-sky-50/40 ${r.is_active ? "" : "opacity-60"}`}>
                    {/* Name first and largest — it is what people scan for — with our
                        code and their references on the line under it. */}
                    {/* Width is fixed on an inner div, not the cell: in an auto-layout
                        table a cell's max-width is ignored, so a long name stretched the
                        column instead of wrapping. Two lines, then ellipsis. */}
                    <td className="px-3 py-2.5">
                      <div className="w-44">
                      <button onClick={() => router.push(`/user-master/agency-master/${r.id}`)}
                        className="block w-full text-left text-[12px] font-semibold text-gray-900 hover:text-sky-700 leading-snug line-clamp-2 break-words"
                        title={r.name}>
                        {r.name}
                      </button>
                      <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                        {r.agency_code && (
                          <span className="px-1.5 py-px rounded bg-sky-50 ring-1 ring-sky-100 text-sky-700 text-[10px] font-mono font-semibold whitespace-nowrap" title="Agency Code">
                            {r.agency_code}
                          </span>
                        )}
                        {(r.customer_code || r.account_code) && (
                          <span className="text-[10px] font-mono text-gray-400 whitespace-nowrap">
                            {[r.customer_code, r.account_code && `A/c ${r.account_code}`].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </div>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <p className="text-[11px] text-gray-700">{r.branch_name || r.city || "—"}</p>
                      <p className="text-[10px] font-mono text-gray-400">{r.branch_code}</p>
                    </td>
                    <td className="px-3 py-2.5"><ChannelPills scope={r.channels} /></td>
                    {/* One terms column: a row is one channel, so a second, almost
                        always empty column only cost width. Legacy BOTH rows stack. */}
                    <td className="px-3 py-2.5">
                      <div className="flex flex-col gap-2">
                        {scope.map(ch => byChannel[ch]
                          ? <TermsCell key={ch} t={byChannel[ch]} />
                          : <button key={ch} onClick={() => router.push(`/user-master/agency-master/${r.id}`)}
                              className="text-[10px] font-semibold text-sky-600 hover:underline text-left whitespace-nowrap">Set {ch} terms</button>)}
                      </div>
                    </td>
                    <td className="px-3 py-2.5"><ServiceRatesCell r={r} /></td>
                    {/* "Unregistered" and "—" say different things: the first is an
                        answer, the second is a blank nobody has filled in yet. */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <p className="text-[11px] font-mono text-gray-700">
                        {r.gst_number || (r.gst_registered
                          ? <span className="font-sans text-amber-600">GST not entered</span>
                          : <span className="font-sans text-gray-400">Unregistered</span>)}
                      </p>
                      <p className="text-[10px] font-mono text-gray-400">{r.pan_number ? `PAN ${r.pan_number}` : "No PAN"}</p>
                    </td>
                    <td className="px-3 py-2.5 max-w-[180px]">
                      <p className="text-[11px] text-gray-700 truncate" title={r.contact_phone ?? ""}>{r.contact_phone || "—"}</p>
                      {r.contact_email && (
                        <p className="text-[10px] text-gray-400 truncate" title={r.contact_email}>{r.contact_email}</p>
                      )}
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <MasterCell
                        row={r}
                        busy={requesting === r.id}
                        onRequest={() => requestMaster(r)}
                      />
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap"><ActiveBadge active={r.is_active} onClick={() => toggle(r)} /></td>
                    {/* Pinned right so the actions stay reachable however wide the table scrolls. */}
                    <td className="px-2 py-2.5 sticky right-0 bg-white group-hover:bg-sky-50 shadow-[-6px_0_6px_-6px_rgba(0,0,0,0.12)]">
                      <div className="flex items-center gap-0.5">
                        {/* The way through to Invoicing, as on Employee / Corporate Master. */}
                        <button onClick={() => router.push(`/billing/agency/${r.id}`)}
                          className="p-1.5 hover:bg-green-50 rounded-lg text-green-600"
                          title="Bill this agency"><ReceiptIndianRupee className="w-3.5 h-3.5" /></button>
                        <button onClick={() => router.push(`/user-master/agency-master/${r.id}`)}
                          className="p-1.5 hover:bg-emerald-50 rounded-lg text-emerald-500 hover:text-emerald-700"
                          title="Account — payments, terms history and billing cycles"><Wallet className="w-3.5 h-3.5" /></button>
                        <button onClick={() => setModal(r)} className="p-1.5 hover:bg-blue-50 rounded-lg text-blue-400 hover:text-blue-600" title="Edit"><Edit2 className="w-3.5 h-3.5" /></button>
                        <button onClick={() => setPendingDelete(r)} className="p-1.5 hover:bg-red-50 rounded-lg text-red-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {pendingDelete && (
        <ConfirmDialog
          title="Delete agency"
          confirmLabel="Delete agency"
          onConfirm={confirmDelete}
          onClose={() => setPendingDelete(null)}
        >
          <p>
            Delete <span className="font-semibold text-gray-900">{pendingDelete.name}</span>{" "}
            <span className="text-gray-400">
              ({[pendingDelete.agency_code, pendingDelete.branch_name || pendingDelete.city || pendingDelete.branch_code, pendingDelete.channels]
                .filter(Boolean).join(" · ")})
            </span>?
          </p>
          <p>Its entities and login IDs will be removed too. This cannot be undone.</p>
        </ConfirmDialog>
      )}

      {modal !== false && (
        <AgencyModal agency={modal} onClose={() => setModal(false)}
          onSaved={() => { setModal(false); fetchRows(); }} onRefresh={fetchRows} onGoTo={onGoTo} />
      )}
    </div>
  );
}

/**
 * Where an agency stands with the shared supplier master.
 *
 * Four states, and the difference between the last two matters: a REJECTED
 * request was refused for a reason the user can act on, while UNLISTED simply
 * means nobody has asked yet — an agency typed in before this flow existed, or
 * one that arrived in an XLS upload, which does not file requests of its own.
 * Both keep working either way; being outside the master limits nothing except
 * whether other workspaces can find the vendor.
 */
function MasterCell({
  row, busy, onRequest,
}: {
  row: AgencyRow;
  busy: boolean;
  onRequest: () => void;
}) {
  const state = masterState(row);

  if (state === "in_master") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700 bg-emerald-50 ring-1 ring-emerald-200 rounded-full px-2 py-0.5"
        title="This vendor is in the shared supplier master.">
        <Check className="w-3 h-3" /> In master
      </span>
    );
  }

  if (state === "pending") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-amber-800 bg-amber-50 ring-1 ring-amber-200 rounded-full px-2 py-0.5"
        title="Sent to the platform admin. The agency works normally while it waits.">
        <Clock className="w-3 h-3" /> Awaiting approval
      </span>
    );
  }

  if (state === "rejected") {
    return (
      <div className="flex flex-col gap-1 items-start">
        <span
          className="inline-flex items-center gap-1 text-[10px] font-semibold text-red-700 bg-red-50 ring-1 ring-red-200 rounded-full px-2 py-0.5 cursor-help"
          title={row.supplier_request_reason || "The platform admin declined this request."}
        >
          <AlertTriangle className="w-3 h-3" /> Declined
        </span>
        {row.supplier_request_reason && (
          <span className="text-[10px] text-gray-400 max-w-48 line-clamp-2" title={row.supplier_request_reason}>
            {row.supplier_request_reason}
          </span>
        )}
        <button onClick={onRequest} disabled={busy}
          className="text-[10px] font-semibold text-sky-600 hover:underline disabled:opacity-50">
          {busy ? "Sending…" : "Fix and resubmit"}
        </button>
      </div>
    );
  }

  return (
    <button onClick={onRequest} disabled={busy}
      className="text-[10px] font-semibold text-sky-600 hover:underline disabled:opacity-50"
      title="Ask the platform admin to add this vendor to the shared master, so every workspace can find it.">
      {busy ? "Sending…" : "Request master entry"}
    </button>
  );
}

/** One channel's terms as typed into the form — all strings until save. */
type TermsDraft = { agency_type: string; billing_cycle: string; deposit_amount: string; usage_percent: string; credit_limit: string };
const emptyTerms = (): TermsDraft => ({ agency_type: "", billing_cycle: "", deposit_amount: "", usage_percent: "", credit_limit: "" });

function AgencyModal({
  agency, onClose, onSaved, onRefresh, onGoTo,
}: {
  agency: AgencyRow | null;
  onClose: () => void;
  onSaved: () => void;
  onRefresh: () => void;
  onGoTo?: (tab: "entities" | "logins", agencyId: number) => void;
}) {
  const isEdit = !!agency;
  const [tab, setTab] = useState<"single" | "multi" | "xls">("single");
  const [suppliers, setSuppliers] = useState<SupplierFull[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // Set on 201 so the modal can offer the natural next steps rather than just closing.
  const [created, setCreated] = useState<AgencyRow | null>(null);

  const [vendorName, setVendorName] = useState("");
  const [supplierId, setSupplierId] = useState<number | null>(null);
  // The master holds a couple of thousand agencies and the trade has lakhs, so
  // "it isn't in the list" is ordinary rather than exceptional. In manual mode the
  // picker becomes a plain name box, the branch key defaults to MAIN, and the save
  // files a supplier-master request so the platform admin can add the vendor for
  // everyone. The agency itself is usable the moment it is created.
  const [manualEntry, setManualEntry] = useState(false);
  // Set only by "Also add on the other channel" after a hand-entered create, so
  // the second row attaches to the first row's request instead of raising another.
  const [reuseRequestId, setReuseRequestId] = useState<number | null>(null);
  const [channels, setChannels] = useState<Channel>("GDS");
  // Keyed by channel so switching GDS → LCC → GDS does not lose what was typed.
  const [terms, setTerms] = useState<Record<Channel, TermsDraft>>({ GDS: emptyTerms(), LCC: emptyTerms() });
  const [form, setForm] = useState({
    name: agency?.name ?? "",
    branch_code: agency?.branch_code ?? "",
    branch_name: agency?.branch_name ?? "",
    address: agency?.address ?? "",
    // Through canonicalState so a row stored as "NEW DELHI" or "Orissa" selects
    // the picker entry it means instead of showing an empty box.
    state: canonicalState(agency?.state) || "",
    city: agency?.city ?? "",
    region_chapter: agency?.region_chapter ?? "",
    // Registered by default when a GSTIN is already on the row, so opening an
    // existing agency shows its number rather than hiding it behind an off toggle.
    gst_registered: agency?.gst_registered ?? !!agency?.gst_number,
    gst_number: agency?.gst_number ?? "",
    pan_number: agency?.pan_number ?? "",
    contact_phone: agency?.contact_phone ?? "",
    contact_email: agency?.contact_email ?? "",
    notes: agency?.notes ?? "",
    agency_code: agency?.agency_code ?? "",
    customer_code: agency?.customer_code ?? "",
    account_code: agency?.account_code ?? "",
    // Both service rates, held as strings like every other input here. A stored 0
    // must survive the round-trip as "0" and not become "" — `?? ""` on the value
    // rather than `|| ""`, because a deliberate zero rate is a real answer.
    vendor_service_charge_type: agency?.vendor_service_charge_type ?? "",
    vendor_service_charge_value:
      agency?.vendor_service_charge_value != null ? String(agency.vendor_service_charge_value) : "",
    vendor_service_charge_gst: agency?.vendor_service_charge_gst ?? "",
    customer_service_fee_type: agency?.customer_service_fee_type ?? "",
    customer_service_fee_value:
      agency?.customer_service_fee_value != null ? String(agency.customer_service_fee_value) : "",
    customer_service_fee_gst: agency?.customer_service_fee_gst ?? "",
    is_active: agency?.is_active ?? true,
  });
  const set = (k: keyof typeof form, v: string | boolean) => setForm(p => ({ ...p, [k]: v }));

  // ── Agency Code ──────────────────────────────────────────────────────────
  // System-generated by default: the box shows what the server WOULD issue and the
  // create sends nothing, so the server issues afresh and two open forms cannot
  // both take the number they were shown. Unticking lets the user type one; the
  // server then checks it, pads it to the current pattern, and makes its pattern
  // the one later auto codes continue. An edit always starts in manual mode, on
  // the code the agency already has.
  const [autoCode, setAutoCode] = useState(!isEdit);
  const [codeHint, setCodeHint] = useState<{ code: string; pattern: string | null; error?: string | null; shared?: boolean } | null>(null);

  useEffect(() => {
    if (!autoCode) return;
    const t = setTimeout(() => {
      api.get<{ code: string; pattern: string; shared_with_sibling: boolean }>("/agencies/next-code", {
        params: { name: form.name.trim() || undefined, branch_code: form.branch_code.trim() || undefined },
      }).then(r => setCodeHint({ code: r.data.code, pattern: r.data.pattern, shared: r.data.shared_with_sibling }))
        .catch(() => setCodeHint(null));
    }, 250);
    return () => clearTimeout(t);
  }, [autoCode, form.name, form.branch_code]);

  useEffect(() => {
    if (autoCode) return;
    const typed = form.agency_code.trim();
    if (!typed || (isEdit && typed === (agency?.agency_code ?? ""))) { setCodeHint(null); return; }
    const t = setTimeout(() => {
      api.get<{ code: string; pattern: string | null; error: string | null }>("/agencies/check-code", {
        params: {
          code: typed,
          name: form.name.trim() || undefined,
          branch_code: form.branch_code.trim() || undefined,
          exclude_id: agency?.id,
        },
      }).then(r => setCodeHint(r.data)).catch(() => setCodeHint(null));
    }, 300);
    return () => clearTimeout(t);
  }, [autoCode, form.agency_code, form.name, form.branch_code, isEdit, agency]);

  // Live per-field problems, shown under the box being typed into. Deliberately
  // separate from `error` (which is one line above the buttons): a GSTIN whose
  // check digit is wrong needs to be pointed AT the GSTIN, not summarised.
  //
  // The *Typing* variants stay quiet until the value is long enough to judge —
  // see lib/indiaTax. The strict versions run again in taxProblem() on save, so
  // a half-typed value is caught there rather than slipping through.
  const panProblem = panTypingError(form.pan_number);
  // A malformed PAN is not worth cross-checking the GSTIN against — it would
  // report "characters 3-12 do not match" on top of the PAN error already shown.
  const gstProblem = form.gst_registered
    ? gstinTypingError(form.gst_number, { pan: panProblem ? "" : form.pan_number, state: form.state })
    : "";

  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [pickSearch, setPickSearch] = useState("");
  const [result, setResult] = useState<{ created: number; skipped: number } | null>(null);
  // Bulk add applies ONE arrangement to every picked agency, so it offers a
  // single channel choice rather than the per-channel blocks — mixed terms across
  // forty agencies is not something one form can honestly collect. Run it twice,
  // once per channel, to onboard the same set on both.
  const [multiChannel, setMultiChannel] = useState<Channel>("GDS");

  useEffect(() => {
    if (!isEdit) {
      api.get<SupplierFull[]>("/suppliers/", { params: { limit: 5000 } })
        .then(r => setSuppliers(r.data)).catch(() => setSuppliers([]));
    }
  }, [isEdit]);

  // One entry per agency name, each holding its branch rows. ~2,339 names out of
  // ~2,480 master rows, so most have exactly one branch.
  const vendors = useMemo(() => {
    const m = new Map<string, SupplierFull[]>();
    for (const s of suppliers) {
      const key = (s.name ?? "").trim();
      if (!key) continue;
      const existing = m.get(key);
      if (existing) existing.push(s); else m.set(key, [s]);
    }
    return m;
  }, [suppliers]);

  const vendorNames = useMemo(
    () => [...vendors.keys()].sort((a, b) => a.localeCompare(b)),
    [vendors],
  );

  const branches = vendorName ? (vendors.get(vendorName) ?? []) : [];

  const branchLabel = (s: SupplierFull) =>
    [s.branch, s.city, s.region_chapter].filter(Boolean).join(" — ") || s.code || `Branch ${s.id}`;

  // Merge rather than replace, so terms already entered survive a re-pick.
  const applyBranch = (s: SupplierFull) => {
    setSupplierId(s.id);
    setForm(p => ({
      ...p,
      name: s.name ?? "",
      branch_code: (s.code ?? "").trim() || "MAIN",
      branch_name: s.branch || s.city || "",
      // address_1..3 are one postal address split across three columns, not
      // alternatives. State has no source in the master — it is typed in.
      address: [s.address_1, s.address_2, s.address_3].map(x => (x ?? "").trim()).filter(Boolean).join(", "),
      city: s.city ?? "",
      region_chapter: s.region_chapter ?? "",
      // Upper-cased on the way in so the checks below compare like with like —
      // the master is inconsistent about case and these are checked character
      // by character against each other.
      gst_registered: p.gst_registered || !!normaliseTaxId(s.gst_number),
      gst_number: normaliseTaxId(s.gst_number),
      pan_number: normaliseTaxId(s.pan_number),
      contact_phone: s.contact_phone || s.telephone_mobile || "",
      contact_email: s.contact_email || s.email_address || s.alternate_email_id || "",
      notes: s.notes ?? "",
    }));
  };

  const pickVendor = (name: string) => {
    setVendorName(name);
    setManualEntry(false);
    // Picking from the master ends any hand-entered thread, including a request
    // carried over from the other channel.
    setReuseRequestId(null);
    const list = vendors.get(name) ?? [];
    if (list.length > 0) applyBranch(list[0]);
    else setSupplierId(null);
  };

  /** Switch to typing the agency in, carrying across whatever was already there.
   *  `typedName` comes from the dropdown's "+ Add new agency" — what the user was
   *  searching for is almost always the name they mean, so it pre-fills the box. */
  const startManualEntry = (typedName?: string) => {
    setManualEntry(true);
    setSupplierId(null);
    setVendorName("");
    setForm(p => ({
      ...p,
      name: typedName?.trim() ? typedName.trim() : p.name,
      branch_code: p.branch_code.trim() || "MAIN",
    }));
  };

  /**
   * The name box is the authority in manual mode, and it is also editable after a
   * master pick — so a picked vendor whose name is then changed is no longer that
   * vendor. Drop `supplier_id` when that happens, or the agency would be saved
   * under one name while claiming provenance from a different master row, with
   * nothing reconciling the two.
   */
  const setName = (v: string) => {
    setForm(p => ({ ...p, name: v }));
    if (!manualEntry && supplierId !== null && v.trim().toLowerCase() !== vendorName.trim().toLowerCase()) {
      setSupplierId(null);
      setVendorName("");
      setManualEntry(true);
    }
  };

  /**
   * Close matches for a typed name — the duplicate defence.
   *
   * The master is one row per BRANCH, so "Riya Travel & Tours" legitimately exists
   * fourteen times; a server-side uniqueness rule would reject valid requests.
   * Catching a near-miss here, before it reaches the admin, is the only guard that
   * can work — and it stays advisory, because the user is the one who knows
   * whether their agency really is the one on screen.
   */
  const nearMatches = useMemo(() => {
    const q = form.name.trim().toLowerCase();
    if (!manualEntry || q.length < 3) return [];

    // Matching on any shared word is worthless here: almost every name in the
    // master contains "travels" or "tours", so "Balaji Travels Mumbai" would
    // surface every agency in India. Only DISTINCTIVE words count — the ones that
    // identify a company rather than describe its trade.
    const tokens = q.split(/\s+/).filter(w => w.length > 2 && !GENERIC_NAME_WORDS.has(w));

    const scored = suppliers
      .map(s => {
        const n = (s.name ?? "").toLowerCase();
        // A whole-string containment is the strongest signal there is. Failing
        // that, weight by WHICH words match, not just how many: a name leads with
        // the company ("Balaji Travels Mumbai"), so a hit on the first word counts
        // for more than one on a trailing city — otherwise every agency in Mumbai
        // outranks the actual Balaji.
        const hits = tokens.reduce(
          (sum, w, i) => (n.includes(w) ? sum + (tokens.length - i) : sum), 0,
        );
        return { s, score: n.includes(q) ? 100 : hits };
      })
      .filter(x => x.score > 0);

    scored.sort((a, b) => b.score - a.score || a.s.name.localeCompare(b.s.name));
    return scored.slice(0, 5).map(x => x.s);
  }, [manualEntry, form.name, suppliers]);

  const setTerm = (ch: Channel, k: keyof TermsDraft, v: string) =>
    setTerms(p => ({ ...p, [ch]: { ...p[ch], [k]: v } }));

  const setAgencyType = (ch: Channel, v: string) =>
    setTerms(p => ({
      ...p,
      // Drop what no longer applies so a stale deposit can't ride along.
      [ch]: {
        ...p[ch],
        agency_type: v,
        deposit_amount: v === "cash" ? p[ch].deposit_amount : "",
        usage_percent: v === "cash" ? p[ch].usage_percent : "",
        credit_limit: v === "credit" ? p[ch].credit_limit : "",
      },
    }));

  /** State and the tax ids, checked as a set on save — none is right on its own.
   *  Uses the STRICT checks, not the typing-aware ones, so a value abandoned
   *  half-typed is refused here rather than posted. */
  const taxProblem = (): string => {
    if (!form.state) return "Pick the state — a GSTIN's first two characters are checked against it.";
    const pan = panError(form.pan_number);
    if (pan) return pan;
    if (form.gst_registered && !form.gst_number.trim()) {
      return "This agency is marked GST registered — enter its GSTIN, or turn the toggle off.";
    }
    return form.gst_registered
      ? gstinError(form.gst_number, { pan: form.pan_number, state: form.state })
      : "";
  };

  const saveSingle = async () => {
    if (!form.name.trim()) { setError("Agency is required."); return; }
    // `branch_code` is only ever written by applyBranch, so an empty one on a
    // master-picked create means no branch was chosen. In manual mode there is no
    // branch to pick — startManualEntry defaults it to MAIN, the key the model
    // reserves for a hand-entered agency.
    if (!isEdit && !manualEntry && !form.branch_code.trim()) { setError("Pick a branch."); return; }

    if (!autoCode && !form.agency_code.trim()) {
      setError("Enter an agency code, or tick “Auto-generate”."); return;
    }
    if (!autoCode && codeHint?.error) { setError(codeHint.error); return; }

    const bad = taxProblem();
    if (bad) { setError(bad); return; }

    // Both directions' rates, validated here rather than on the server so the
    // message names the side that is wrong. A direction with no type sends three
    // nulls: the server drops a half-set rate either way, but a rate silently
    // dropped after the user typed it is the one outcome worth catching first.
    const feeFields: Record<string, string | number | null> = {};
    for (const d of SERVICE_FEE_DIRECTIONS) {
      const kind = form[`${d.prefix}_type` as keyof typeof form] as string;
      const raw = String(form[`${d.prefix}_value` as keyof typeof form] ?? "").trim();
      if (!kind) {
        feeFields[`${d.prefix}_type`] = null;
        feeFields[`${d.prefix}_value`] = null;
        feeFields[`${d.prefix}_gst`] = null;
        continue;
      }
      if (!raw) { setError(`${d.heading}: enter the ${d.label.toLowerCase()} amount, or set the type back to None.`); return; }
      if (!Number.isFinite(Number(raw))) { setError(`${d.heading}: ${d.label} must be a number.`); return; }
      if (Number(raw) < 0) { setError(`${d.heading}: ${d.label} cannot be negative.`); return; }
      feeFields[`${d.prefix}_type`] = kind;
      feeFields[`${d.prefix}_value`] = Number(raw);
      // Blank means the select was never touched, and its own default is exclusive.
      feeFields[`${d.prefix}_gst`] =
        (form[`${d.prefix}_gst` as keyof typeof form] as string) || "exclusive";
    }

    // An unregistered agency posts no GSTIN at all rather than whatever is still
    // sitting in the hidden box — the two facts have to agree, and "unregistered"
    // is the one just asserted.
    const taxFields = {
      state: form.state,
      gst_registered: form.gst_registered,
      gst_number: form.gst_registered ? normaliseTaxId(form.gst_number) : null,
      pan_number: normaliseTaxId(form.pan_number) || null,
    };

    if (isEdit && agency) {
      // Identity only — terms live on the Account page now.
      setSaving(true); setError("");
      try {
        await api.patch(`/agencies/${agency.id}`, {
          name: form.name.trim(), address: form.address || null, ...taxFields,
          city: form.city || null, region_chapter: form.region_chapter || null,
          contact_phone: form.contact_phone || null, contact_email: form.contact_email || null,
          // Editable here, unlike the terms — see the form's own note on why.
          ...feeFields,
          notes: form.notes || null, is_active: form.is_active,
          customer_code: form.customer_code.trim() || null, account_code: form.account_code.trim() || null,
          // Only when changed — re-sending the stored code would be a no-op anyway.
          ...(form.agency_code.trim() !== (agency.agency_code ?? "") ? { agency_code: form.agency_code.trim() } : {}),
        });
        onSaved();
      } catch (e) { setError(apiError(e)); }
      finally { setSaving(false); }
      return;
    }

    // One block, for the declared channel. The loop stays because the message has
    // to name the channel — "pick cash or credit" alone does not say which
    // arrangement is incomplete once an agency exists on both.
    const payloadTerms = [];
    for (const ch of channelsOf(channels)) {
      const t = terms[ch];
      if (!t.agency_type) { setError(`${ch}: pick Cash or Credit.`); return; }
      if (!t.billing_cycle) { setError(`${ch}: pick a billing cycle.`); return; }
      const numeric: [keyof TermsDraft, string][] = [
        ["credit_limit", "Limit"], ["deposit_amount", "Deposit"], ["usage_percent", "Usage %"],
      ];
      for (const [key, label] of numeric) {
        const raw = t[key].trim();
        if (!raw) continue;
        if (!Number.isFinite(Number(raw))) { setError(`${ch}: ${label} must be a number.`); return; }
        if (Number(raw) < 0) { setError(`${ch}: ${label} cannot be negative.`); return; }
      }
      if (t.agency_type === "cash" && !t.deposit_amount.trim()) {
        setError(`${ch} is cash — enter the deposit amount.`); return;
      }
      if (t.agency_type === "credit" && !t.credit_limit.trim()) {
        setError(`${ch} is credit — enter the credit limit.`); return;
      }
      const num = (v: string) => (v.trim() === "" ? null : Number(v));
      payloadTerms.push({
        channel: ch,
        agency_type: t.agency_type,
        billing_cycle: t.billing_cycle,
        credit_limit: num(t.credit_limit),
        deposit_amount: num(t.deposit_amount),
        usage_percent: num(t.usage_percent),
      });
    }

    setSaving(true); setError("");
    try {
      const { data } = await api.post<AgencyRow>("/agencies/", {
        name: form.name.trim(),
        supplier_id: supplierId,
        branch_code: form.branch_code.trim() || "MAIN",
        branch_name: form.branch_name || null,
        address: form.address || null,
        ...taxFields,
        city: form.city || null,
        region_chapter: form.region_chapter || null,
        contact_phone: form.contact_phone || null,
        contact_email: form.contact_email || null,
        ...feeFields,
        notes: form.notes || null,
        // Null = let the server issue it (auto mode).
        agency_code: autoCode ? null : form.agency_code.trim(),
        customer_code: form.customer_code.trim() || null,
        account_code: form.account_code.trim() || null,
        is_active: form.is_active,
        channels,
        terms: payloadTerms,
        // Typed in rather than picked: ask the platform admin to add the vendor to
        // the shared master. `reuseRequestId` is set when this is the same vendor's
        // other channel — one vendor gets one request, not one per channel.
        request_master_entry: manualEntry && !supplierId,
        supplier_request_id: reuseRequestId,
      });
      setCreated(data);
      onRefresh();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const saveMulti = async () => {
    if (picked.size === 0) { setError("Select at least one agency."); return; }
    const t = terms.GDS;
    if (!t.agency_type || !t.billing_cycle) { setError("Set the terms every selected agency will get."); return; }
    if (t.agency_type === "cash" && !t.deposit_amount.trim()) { setError("Cash — enter the deposit amount."); return; }
    if (t.agency_type === "credit" && !t.credit_limit.trim()) { setError("Credit — enter the credit limit."); return; }

    setSaving(true); setError(""); setResult(null);
    const num = (v: string) => (v.trim() === "" ? null : Number(v));
    try {
      const { data } = await api.post<{ created: number; skipped: number }>(
        "/agencies/from-suppliers", {
          supplier_ids: Array.from(picked),
          channels: multiChannel,
          terms: channelsOf(multiChannel).map(ch => ({
            channel: ch,
            agency_type: t.agency_type,
            billing_cycle: t.billing_cycle,
            credit_limit: num(t.credit_limit),
            deposit_amount: num(t.deposit_amount),
            usage_percent: num(t.usage_percent),
          })),
        });
      setResult(data);
      setPicked(new Set());
      if (data.created > 0) onRefresh();
    } catch (e) { setError(apiError(e)); }
    finally { setSaving(false); }
  };

  const vendorRows = useMemo(
    () => vendorNames.map(n => vendors.get(n)![0]),
    [vendorNames, vendors],
  );
  const filteredVendors = pickSearch.trim()
    ? vendorRows.filter(s => s.name.toLowerCase().includes(pickSearch.trim().toLowerCase()))
    : vendorRows;

  /** The terms block, rendered once per declared channel. */
  const termsBlock = (ch: Channel, heading: string) => {
    const t = terms[ch];
    return (
      <div key={ch} className="rounded-lg border border-gray-200 bg-gray-50/50 p-3 space-y-3">
        <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide">{heading}</p>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={LABEL}>Type *</label>
            <select value={t.agency_type} onChange={e => setAgencyType(ch, e.target.value)} className={INPUT}>
              <option value="">— Select —</option>
              {AGENCY_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </div>
          <div><label className={LABEL}>Billing Cycle *</label>
            <select value={t.billing_cycle} onChange={e => setTerm(ch, "billing_cycle", e.target.value)} className={INPUT}>
              <option value="">— Select —</option>
              {BILLING_CYCLES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
        </div>

        {t.agency_type === "cash" && (
          <>
            <div><label className={LABEL}>Deposit (₹) *</label>
              <input type="number" min="0" value={t.deposit_amount}
                onChange={e => setTerm(ch, "deposit_amount", e.target.value)}
                placeholder="e.g. 10000000" className={INPUT} />
              <p className="text-[10px] text-gray-400 mt-1">In cash the limit is the deposit — the agency pays first, so its balance is the money in.</p>
            </div>
            <div><label className={LABEL}>Usage %</label>
              <input type="number" min="0" value={t.usage_percent}
                onChange={e => setTerm(ch, "usage_percent", e.target.value)}
                placeholder="e.g. 90" className={INPUT} />
              <p className="text-[10px] text-gray-400 mt-1">Notify once this share of the deposit is used. May go above 100 — 110 warns after they run 10% past it.</p>
            </div>
          </>
        )}

        {t.agency_type === "credit" && (
          <div><label className={LABEL}>Limit (₹) *</label>
            <input type="number" min="0" value={t.credit_limit}
              onChange={e => setTerm(ch, "credit_limit", e.target.value)}
              placeholder="e.g. 5000000" className={INPUT} />
            <p className="text-[10px] text-gray-400 mt-1">On credit the limit stands on its own — invoices go out on the billing cycle.</p>
          </div>
        )}
      </div>
    );
  };

  /** One direction's rate — Type, then Value, then the GST question.
   *
   *  IN THAT ORDER FOR A REASON, the same one the tax block above is ordered by:
   *  each answer decides how the next box reads. The type decides whether the value
   *  is a % or a ₹ amount, and there is nothing to ask about GST until there is an
   *  amount to tax — so both later fields stay hidden until the type is picked,
   *  rather than sitting there inviting a half-filled rate the server would drop.
   */
  const serviceFeeBlock = (d: (typeof SERVICE_FEE_DIRECTIONS)[number]) => {
    const typeKey = `${d.prefix}_type` as keyof typeof form;
    const valueKey = `${d.prefix}_value` as keyof typeof form;
    const gstKey = `${d.prefix}_gst` as keyof typeof form;
    const kind = form[typeKey] as string;

    return (
      <div key={d.prefix} className="rounded-lg border border-gray-200 bg-gray-50/50 p-3 space-y-3">
        <div>
          <p className="text-[11px] font-bold text-gray-700 uppercase tracking-wide">{d.heading}</p>
          <p className="text-[10px] text-gray-400 mt-0.5">{d.hint}</p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div><label className={LABEL}>{d.label} Type</label>
            <select value={kind} onChange={e => set(typeKey, e.target.value)} className={INPUT}>
              <option value="">— None —</option>
              {SERVICE_FEE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          {kind && (
            <div><label className={LABEL}>{kind === "percentage" ? "Value (%)" : "Value (₹)"} *</label>
              <input type="number" min="0" step="any" value={form[valueKey] as string}
                onChange={e => set(valueKey, e.target.value)}
                placeholder={kind === "percentage" ? "e.g. 2" : "e.g. 250"} className={INPUT} />
            </div>
          )}
        </div>

        {kind && (
          <div><label className={LABEL}>GST on this {d.label.toLowerCase()} *</label>
            <select value={(form[gstKey] as string) || "exclusive"}
              onChange={e => set(gstKey, e.target.value)} className={INPUT}>
              {GST_TREATMENTS.map(g => <option key={g.value} value={g.value}>{g.label}</option>)}
            </select>
            <p className="text-[10px] text-gray-400 mt-1">
              {(form[gstKey] as string) === "inclusive"
                ? "The amount above already contains GST — it is divided out, so ₹1,000 is ₹847.46 plus ₹152.54 tax."
                : "GST is added on top of the amount above — ₹1,000 becomes ₹1,180."}
            </p>
          </div>
        )}
      </div>
    );
  };

  // ── after a successful create ──────────────────────────────────────────
  // The channel this branch is NOT yet on, if there is one. Null for a legacy
  // BOTH row, which already covers everything.
  const otherChannel: Channel | null =
    created && created.channels !== "BOTH" ? (created.channels === "GDS" ? "LCC" : "GDS") : null;

  /** Reopen the form on the other channel with the identity already filled in.
   *  `terms` is keyed by channel, so the block that appears is empty and the one
   *  just submitted is untouched.
   *
   *  A hand-entered vendor carries its master request across rather than filing a
   *  second one. It is ONE vendor being added to the master; the fact that we hold
   *  it as two agency rows is our own bookkeeping, and the admin should not be
   *  asked to approve the same company twice.
   *
   *  THE SERVICE RATES CARRY ACROSS, unlike the terms — they live in `form`, which
   *  is left alone here. That is the useful default (it is the same vendor, and the
   *  rate usually is too) and it stays correct because they are still saved onto
   *  the new row, per channel; anyone whose LCC rate differs edits the two boxes
   *  before saving, which is less work than retyping both. */
  const addOnOtherChannel = () => {
    if (!otherChannel) return;
    setReuseRequestId(created?.supplier_request_id ?? null);
    setChannels(otherChannel);
    // Same branch, so the same code — the server reuses it for a blank auto create.
    setAutoCode(true);
    if (created?.agency_code) setCodeHint({ code: created.agency_code, pattern: null, shared: true });
    setCreated(null);
    setError("");
  };

  if (created) {
    return (
      <ModalShell title="Agency added" onClose={onSaved}>
        <div className="space-y-4">
          <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2.5">
            <p className="text-[12px] font-semibold text-green-800">
              {created.name} · {created.branch_name || created.branch_code} added.
            </p>
            <p className="text-[11px] text-green-700 mt-0.5">
              {channelsOf(created.channels).map(c => {
                const t = created.terms.find(x => x.channel === c);
                return t ? `${c} ${t.agency_type}` : c;
              }).join(" · ")}
            </p>
          </div>
          {/* The other channel is a SECOND agency, not a setting on this one — so
              offer to add it here, carrying the identity across. Retyping the
              state, PAN and GSTIN of the branch just onboarded is the friction
              that made a "Both" card look necessary in the first place. */}
          {otherChannel && (
            <button onClick={addOnOtherChannel}
              className="w-full flex items-center justify-center gap-1.5 border border-sky-200 bg-sky-50 rounded-lg py-2.5 text-xs font-semibold text-sky-700 hover:bg-sky-100">
              Also add {created.name} on {otherChannel} <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )}

          <p className="text-[11px] text-gray-500">
            Next, give it the branches it books from and the credentials it books with.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <button onClick={() => onGoTo?.("entities", created.id)} disabled={!onGoTo}
              className="flex items-center justify-center gap-1.5 border border-gray-200 rounded-lg py-2.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-40">
              Add Entities <ArrowRight className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => onGoTo?.("logins", created.id)} disabled={!onGoTo}
              className="flex items-center justify-center gap-1.5 border border-gray-200 rounded-lg py-2.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-40">
              Add Login IDs <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
          <button onClick={onSaved} className="w-full text-white rounded-lg py-2 text-sm font-semibold"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>Done</button>
        </div>
      </ModalShell>
    );
  }

  const manualForm = (
    <div className="space-y-3">
      {!isEdit && (
        <>
          {/* Channel first — it decides which terms block appears below, and it is
              part of what makes this row unique. The same branch can be added
              again on the other channel; it becomes a second agency. */}
          <div>
            <label className={LABEL}>Channel *</label>
            <div className="grid grid-cols-2 gap-2">
              {CHANNEL_CHOICES.map(c => (
                <button key={c.value} type="button" onClick={() => setChannels(c.value)}
                  className={`rounded-lg border px-2 py-2 text-center transition ${
                    channels === c.value
                      ? "border-sky-500 bg-sky-50 ring-1 ring-sky-400"
                      : "border-gray-200 hover:bg-gray-50"
                  }`}>
                  <span className={`block text-[12px] font-bold ${channels === c.value ? "text-sky-700" : "text-gray-700"}`}>{c.label}</span>
                  <span className="block text-[9px] leading-tight text-gray-400 mt-0.5">{c.hint}</span>
                </button>
              ))}
            </div>
            <p className="text-[10px] text-gray-400 mt-1">
              Works both? Add it on one channel, then add it again on the other — each keeps
              its own terms, deposit and balance.
            </p>
          </div>

          <div>
            <label className={LABEL}>Agency *</label>
            {manualEntry ? (
              <>
                <div className="rounded-lg border border-sky-200 bg-sky-50 px-2.5 py-2 flex items-start gap-2">
                  <PencilLine className="w-3.5 h-3.5 text-sky-600 mt-0.5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-semibold text-sky-800">Adding a new agency</p>
                    <p className="text-[10px] text-sky-700 leading-snug mt-0.5">
                      Fill in the details below. The agency is yours to use straight away,
                      and it goes to the supplier master as <b>pending approval</b> — once
                      the platform admin approves it, every workspace can find it.
                    </p>
                    <button type="button"
                      onClick={() => { setManualEntry(false); setReuseRequestId(null); }}
                      className="text-[10px] font-semibold text-sky-700 hover:underline mt-1">
                      Back to picking from the list
                    </button>
                  </div>
                </div>
                {reuseRequestId !== null && (
                  <p className="text-[10px] text-gray-400 mt-1">
                    Using the request already raised for this agency on the other channel —
                    the admin will not be asked twice.
                  </p>
                )}
              </>
            ) : (
              <>
                {/* "+ Add new agency" in the dropdown is the manual path: the agency
                    is created for this user at once, and a pending request goes to
                    the supplier master for admin approval. */}
                <SearchSelect value={vendorName} options={vendorNames} onChange={pickVendor}
                  placeholder="Search and select an agency"
                  onAddNew={q => startManualEntry(q)} addNewLabel="Add new agency" />
              </>
            )}
          </div>

          {!manualEntry && branches.length > 0 && (
            <div>
              <label className={LABEL}>Branch *</label>
              <select value={supplierId ?? ""} onChange={e => {
                const s = branches.find(b => b.id === Number(e.target.value));
                if (s) applyBranch(s);
              }} disabled={branches.length === 1} className={branches.length === 1 ? `${INPUT} bg-gray-100 text-gray-500` : INPUT}>
                {branches.map(b => <option key={b.id} value={b.id}>{branchLabel(b)}</option>)}
              </select>
              <p className="text-[10px] text-gray-400 mt-1">
                {branches.length === 1
                  ? "This agency has one branch on record."
                  : `${branches.length} branches on record — each is onboarded separately, with its own terms and balance.`}
              </p>
            </div>
          )}
        </>
      )}

      {/* Through setName, not set("name"): editing this after a master pick means
          the agency is no longer that vendor, so the provenance link is dropped
          rather than left pointing at a different master row. */}
      <div><label className={LABEL}>Agency Name *</label>
        <input value={form.name} onChange={e => setName(e.target.value)} placeholder="e.g. Lords Travels" className={INPUT} /></div>

      {/* Sits under the box that drives it. Advisory, never blocking: the master
          is one row per BRANCH, so the same vendor legitimately appears many times
          and no automatic rule can tell a duplicate from a sibling — only the
          person typing knows which. */}
      {manualEntry && nearMatches.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 -mt-1">
          <p className="text-[11px] font-semibold text-amber-800">
            Similar {nearMatches.length === 1 ? "entry" : "entries"} already in the list
          </p>
          <p className="text-[10px] text-amber-700 mb-1.5">
            Picking one is instant. Carry on typing if none of these is your agency.
          </p>
          <div className="space-y-0.5">
            {nearMatches.map(s => (
              <button key={s.id} type="button" onClick={() => pickVendor(s.name)}
                className="w-full text-left px-2 py-1 rounded text-[11px] text-gray-700 hover:bg-white">
                <span className="font-semibold">{s.name}</span>
                <span className="text-gray-400"> — {branchLabel(s)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between">
          <label className={LABEL}>Agency Code *</label>
          <label className="flex items-center gap-1.5 text-[10px] text-gray-500 cursor-pointer select-none mb-1">
            <input type="checkbox" checked={autoCode} className="accent-sky-600"
              onChange={e => {
                const on = e.target.checked;
                setAutoCode(on);
                setCodeHint(null);
                // Going manual starts from the suggestion, so tweaking it is one keystroke.
                if (!on && !form.agency_code.trim() && codeHint?.code) set("agency_code", codeHint.code);
              }} />
            Auto-generate
          </label>
        </div>
        {autoCode ? (
          <input value={codeHint?.code ?? ""} readOnly placeholder="Generating…"
            className={`${INPUT} bg-gray-100 text-gray-600 font-mono`} />
        ) : (
          <input value={form.agency_code} onChange={e => set("agency_code", e.target.value.toUpperCase().replace(/\s+/g, ""))}
            placeholder="e.g. AG-0001 or LT/DEL/001" maxLength={30}
            className={`${INPUT} font-mono ${codeHint?.error ? "border-red-300" : ""}`} />
        )}
        <p className={`text-[10px] mt-1 ${codeHint?.error ? "text-red-500" : "text-gray-400"}`}>
          {codeHint?.error
            ? codeHint.error
            : autoCode
              ? codeHint?.shared
                ? "Same code as this branch's other channel — one branch, one code."
                : `Next in your sequence${codeHint?.pattern ? ` (${codeHint.pattern})` : ""}. Untick to type your own.`
              : codeHint?.code && codeHint.code !== form.agency_code.trim()
                ? `Will be saved as ${codeHint.code}, to match your pattern.`
                : codeHint?.pattern
                  ? `Pattern ${codeHint.pattern} — auto codes after this one will continue it.`
                  : codeHint
                    ? "No number in this code, so it is a one-off — auto codes keep their own sequence."
                    : "Letters, digits and - / _ . — a number in it sets the pattern later codes follow."}
        </p>
      </div>

      {/* Both optional — neither is needed to save an agency. */}
      <div className="grid grid-cols-2 gap-3">
        <div><label className={LABEL}>Customer Code</label>
          <input value={form.customer_code} onChange={e => set("customer_code", e.target.value.toUpperCase())}
            placeholder="e.g. LORDS-DEL (optional)" maxLength={50} className={INPUT} /></div>
        <div><label className={LABEL}>Account Code</label>
          <input value={form.account_code} onChange={e => set("account_code", e.target.value)}
            placeholder="e.g. ACC-2001 (optional)" maxLength={50} className={INPUT} /></div>
      </div>

      <div><label className={LABEL}>Address</label>
        <input value={form.address} onChange={e => set("address", e.target.value)} placeholder="e.g. 12 Connaught Place" className={INPUT} />
        <p className="text-[10px] text-gray-400 mt-1">This branch&apos;s address. Entities added under it start from this address, state and city.</p></div>

      <div className="grid grid-cols-3 gap-3">
        {/* A picker rather than free text, because this value has to resolve to a
            GST state code — "Delhi" typed three different ways cannot check a
            GSTIN's first two characters. */}
        <div><label className={LABEL}>State *</label>
          {/* Highlighted only once a save has failed — a fresh form is empty, not wrong. */}
          <SearchSelect value={form.state} options={STATE_NAMES} onChange={v => set("state", v)}
            placeholder="Select state" invalid={!form.state && !!error} />
        </div>
        <div><label className={LABEL}>City</label>
          <input value={form.city} onChange={e => set("city", e.target.value)} placeholder="e.g. MUMBAI" className={INPUT} /></div>
        <div><label className={LABEL}>Region / Chapter</label>
          <input value={form.region_chapter} onChange={e => set("region_chapter", e.target.value)} placeholder="e.g. WESTERN REGION" className={INPUT} /></div>
      </div>
      {isEdit && agency?.state && !form.state ? (
        // The row predates the picker and holds something that is not a state —
        // often an IATA chapter copied from the master. Say what was there rather
        // than showing an empty box the user has to guess at.
        <p className="text-[10px] text-amber-600 -mt-1">
          This agency was saved with &quot;{agency.state}&quot;, which is not a state a GSTIN can be
          checked against. Pick the real one.
        </p>
      ) : (
        <p className="text-[10px] text-gray-400 -mt-1">
          The state decides the first two characters of this agency&apos;s GSTIN, so it is required
          even when the agency is not registered.
        </p>
      )}

      {/* ── Tax ids, in the order they can be checked ──────────────────────
          PAN first (it fixes characters 3-12 of the GSTIN), then whether the
          agency is registered at all, and only then the GSTIN itself. */}
      <div><label className={LABEL}>PAN Number</label>
        <input value={form.pan_number}
          onChange={e => set("pan_number", normaliseTaxId(e.target.value))}
          placeholder="e.g. AAPFU0939F" maxLength={10}
          className={`${INPUT} font-mono uppercase tracking-wider ${panProblem ? "border-red-300 bg-red-50" : ""}`} />
        {panProblem && <p className="text-[10px] text-red-500 mt-1">{panProblem}</p>}
      </div>

      <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-3 space-y-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={form.gst_registered}
            onChange={e => {
              set("gst_registered", e.target.checked);
              // Clear the number when the answer becomes "no" — leaving it behind
              // would post a GSTIN for an agency just declared unregistered.
              if (!e.target.checked) set("gst_number", "");
            }}
            className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
          <span className="text-xs font-semibold text-gray-700">Is this agency GST registered?</span>
        </label>

        {form.gst_registered && (
          <div>
            <label className={LABEL}>GST Number *</label>
            <input value={form.gst_number}
              onChange={e => set("gst_number", normaliseTaxId(e.target.value))}
              placeholder={gstinPlaceholder(form.state, form.pan_number)} maxLength={15}
              className={`${INPUT} font-mono uppercase tracking-wider ${gstProblem ? "border-red-300 bg-red-50" : ""}`} />
            {gstProblem
              ? <p className="text-[10px] text-red-500 mt-1">{gstProblem}</p>
              : <p className="text-[10px] text-gray-400 mt-1">
                  Checked against the state above (first two characters), the PAN (characters 3 to 12)
                  and its own check digit — no lookup needed.
                </p>}
          </div>
        )}
      </div>
      {!isEdit && (
        <p className="text-[10px] text-gray-400 -mt-1">The master holds no GST, PAN or state, so enter those yourself.</p>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div><label className={LABEL}>Phone</label>
          <input value={form.contact_phone} onChange={e => set("contact_phone", e.target.value)} placeholder="Contact phone" className={INPUT} /></div>
        <div><label className={LABEL}>Email</label>
          <input value={form.contact_email} onChange={e => set("contact_email", e.target.value)} placeholder="Contact email" className={INPUT} /></div>
      </div>

      {/* ── Commercial terms, one block per declared channel ──────────────── */}
      {!isEdit && (
        <div className="border-t border-gray-100 pt-3 space-y-3">
          {channelsOf(channels).map(ch => termsBlock(ch, `${ch} terms`))}
        </div>
      )}

      {isEdit && (
        <div className="border-t border-gray-100 pt-3">
          <p className="text-[11px] text-gray-500">
            Commercial terms, deposits and channels are managed on the{" "}
            <a href={`/user-master/agency-master/${agency!.id}`} className="font-semibold text-sky-600 hover:underline">Account page</a>
            {" "}— changing them has to close one arrangement and open another at a settled balance.
          </p>
        </div>
      )}

      {/* ── Service charge / service fee, one block per DIRECTION ───────────
          ON EDIT TOO, unlike the terms block above. A fee rate opens no
          commercial period and settles no balance, so it is an ordinary field
          edit that PATCH accepts — it does not belong behind the Account page's
          switch flow.

          Its own section rather than folded into the channel terms: this is not
          a payment term, and putting it beside Cash/Credit/Cycle/Deposit would
          imply it moves with them. It is still per channel, because one agency
          row is already one branch on one channel. */}
      <div className="border-t border-gray-100 pt-3 space-y-3">
        <div>
          <p className="text-xs font-bold text-gray-700">Service charge &amp; fee</p>
          <p className="text-[10px] text-gray-400 mt-0.5">
            Optional, and asked twice because this agency sits on both sides of your books — what they
            charge you is a cost, what you charge them is income. Leave a side blank if it does not apply.
          </p>
        </div>
        {SERVICE_FEE_DIRECTIONS.map(serviceFeeBlock)}
      </div>

      <div><label className={LABEL}>Notes</label>
        <input value={form.notes} onChange={e => set("notes", e.target.value)} placeholder="Remarks" className={INPUT} /></div>
      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
        <span className="text-xs font-semibold text-gray-600">Active</span>
      </label>

      {error && <p className="text-[11px] text-red-500">{error}</p>}

      <div className="flex gap-3 pt-1">
        <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        <button onClick={saveSingle} disabled={saving} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Create Agency"}
        </button>
      </div>
    </div>
  );

  return (
    <ModalShell title={isEdit ? "Edit Agency" : "Add Agency"} onClose={onClose} wide>
      {!isEdit && (
        <div className="flex border-b border-gray-100 mb-4 -mt-1">
          {([["single", "Add Agency"], ["multi", "Bulk Add"], ["xls", "Upload XLS"]] as const).map(([t, lbl]) => (
            <button key={t} onClick={() => { setTab(t); setError(""); }}
              className={`flex-1 py-2.5 text-[11px] font-semibold ${tab === t ? "border-b-2 border-sky-500 text-sky-600" : "text-gray-400"}`}>
              {lbl}
            </button>
          ))}
        </div>
      )}

      {isEdit || tab === "single" ? manualForm
        : tab === "multi" ? (
          <div className="space-y-3">
            <p className="text-[11px] text-gray-500">
              Pick the agencies you work with — each becomes an agency on its first branch, on the channel
              and terms below. Branches already added on that channel are skipped, so running this again
              on the other channel onboards the same set there too.
            </p>
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              The master holds no state, PAN or GST — it has IATA regions like &quot;WESTERN REGION&quot;, not states.
              Agencies added here start without them and need editing before a GSTIN can be verified.
            </p>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input value={pickSearch} onChange={e => setPickSearch(e.target.value)} placeholder="Search agencies…"
                className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400" />
            </div>
            <div className="max-h-52 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-50">
              {filteredVendors.length === 0 ? (
                <p className="px-3 py-6 text-center text-[11px] text-gray-400">No agencies found.</p>
              ) : filteredVendors.map(s => {
                const count = vendors.get(s.name)?.length ?? 1;
                return (
                  <label key={s.id} className="flex items-center gap-2 px-3 py-2 hover:bg-sky-50/40 cursor-pointer">
                    <input type="checkbox" checked={picked.has(s.id)}
                      onChange={e => setPicked(p => { const n = new Set(p); if (e.target.checked) n.add(s.id); else n.delete(s.id); return n; })}
                      className="w-4 h-4 rounded border-gray-300 text-sky-600 focus:ring-sky-400" />
                    <span className="text-[11px] font-semibold text-gray-700">{s.name}</span>
                    {s.city && <span className="text-[10px] text-gray-400">{s.city}</span>}
                    {count > 1 && <span className="text-[10px] text-gray-400">· {count} branches</span>}
                  </label>
                );
              })}
            </div>

            <div>
              <label className={LABEL}>Channel *</label>
              <div className="grid grid-cols-2 gap-2">
                {CHANNEL_CHOICES.map(c => (
                  <button key={c.value} type="button" onClick={() => setMultiChannel(c.value)}
                    className={`rounded-lg border px-2 py-1.5 text-[11px] font-bold transition ${
                      multiChannel === c.value
                        ? "border-sky-500 bg-sky-50 text-sky-700 ring-1 ring-sky-400"
                        : "border-gray-200 text-gray-600 hover:bg-gray-50"
                    }`}>{c.label}</button>
                ))}
              </div>
            </div>
            {termsBlock("GDS", "Terms applied to every selected agency")}

            {result && (
              <div className="rounded-lg border bg-green-50 border-green-200 px-3 py-2 text-[11px] text-green-700">
                {result.created} agenc{result.created === 1 ? "y" : "ies"} added{result.skipped > 0 ? `, ${result.skipped} skipped (already added or unavailable)` : ""}.
              </div>
            )}
            {error && <p className="text-[11px] text-red-500">{error}</p>}

            <div className="flex gap-3 pt-1">
              <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Close</button>
              <button onClick={saveMulti} disabled={saving || picked.size === 0} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
                {saving ? "Adding…" : `Add ${picked.size || ""} Agenc${picked.size === 1 ? "y" : "ies"}`.replace("  ", " ")}
              </button>
            </div>
          </div>
        ) : (
          // One row per agency PER CHANNEL — CHANNELS is GDS or LCC, and a branch
          // that works both gets two rows. STATE is required on every row: the
          // GSTIN is checked against it.
          <UploadBox resource="agencies" templateName="agency_template.xlsx"
            columns="NAME, BRANCH_CODE, BRANCH_NAME, AGENCY_CODE (blank = auto), CUSTOMER_CODE, ACCOUNT_CODE, ADDRESS, STATE, CITY, REGION, PAN, GST_REGISTERED, GST, PHONE, EMAIL, NOTES, CHANNELS, GDS_TYPE, GDS_LIMIT, GDS_DEPOSIT, GDS_USAGE_PCT, GDS_BILLING_CYCLE, LCC_TYPE, LCC_LIMIT, LCC_DEPOSIT, LCC_USAGE_PCT, LCC_BILLING_CYCLE, VENDOR_SERVICE_CHARGE_TYPE / _VALUE / _GST, CUSTOMER_SERVICE_FEE_TYPE / _VALUE / _GST, ACTIVE"
            onDone={onSaved} />
        )}
    </ModalShell>
  );
}
