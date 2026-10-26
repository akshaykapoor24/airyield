"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  Upload, RefreshCw, Trash2, Download, Eye, X, AlertTriangle, ArrowLeft,
  FileSpreadsheet, CheckCircle2, Loader2, ChevronLeft, ChevronRight, FolderOpen, Search, Split,
  Pencil, Check, Database,
} from "lucide-react";
import api from "@/lib/api";
import { downloadEntries } from "@/lib/entriesExport";
import toast from "react-hot-toast";
import { notifyRequired } from "@/lib/requiredFields";
import MultiSelectDropdown from "@/components/ui/MultiSelectDropdown";
import { type TenantAirlineOpt, sameAirlineOnly, toOptions } from "@/lib/tenantAirlineOptions";
import StatementUploadWizard from "@/components/statements/StatementUploadWizard";
import StatementAgencyField, { agencyBlockReason, channelForApiBase } from "@/components/statements/StatementAgencyField";
import { type VendorAgency, loadVendorAgencies } from "@/lib/vendorAgency";
import NdcBillingWorklist from "@/components/statements/ndc/NdcBillingWorklist";
import TpApiBillingWorklist from "@/components/statements/tpapi/TpApiBillingWorklist";
import { ChecksBadge, ChecksPanel, type CheckResult } from "@/components/statements/StatementChecks";
import { formatPeriod, formatUploadedAt, uploadedAtParts } from "@/lib/statementPeriod";

const PAGE = 50;
// The API rejects anything below 3 recognised columns (_MIN_MATCHED_COLUMNS in
// api/v1/statements.py). Between that floor and this number the import succeeds
// but most fields land empty, which is worth saying out loud.
const LOW_MATCH_WARNING = 6;
// The uploads table's Actions column, pinned to the right edge while the rest scrolls.
// Each cell sets its own opaque background so the columns scrolling under it stay hidden.
const PINNED_RIGHT = "sticky right-0 z-10 shadow-[-8px_0_8px_-8px_rgba(15,23,42,0.18)]";
const SELECT_CLS =
  "border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";

type Batch = {
  batch_id: string;
  source_file: string | null;
  uploaded_at: string;
  row_count: number;
  has_file: boolean;
  created_by_name: string | null;
  // Declared at upload, for the LCC types only (requiresAirlineId). Empty for every
  // other type, and for uploads made before the airline was captured.
  airline_name?: string | null;
  airline_code?: string | null;
  airline_ref_ids?: string[];
  // Declared at upload, for the third-party types only (requiresSupplier). Read off the
  // link row's SNAPSHOT, so a renamed vendor doesn't rewrite history. Empty for uploads
  // made before the consolidator was captured.
  supplier_id?: number | null;
  supplier_name?: string | null;
  supplier_branch?: string | null;
  supplier_code?: string | null;
  // Where this upload stands on its way into billing, for the types with a billing flow
  // (supportsBilling — NDC only). Null for every other type, which is what makes the
  // column absent rather than empty. ONE nested field rather than seven flat ones, so the
  // eight types sharing this component do not carry keys that mean nothing to them.
  billing?: BatchBilling | null;
  agency_id?: number | null;
  // Third-party types: the statement period the uploader declared, and the tally off the
  // header — total = new + duplicate: `new` saved as its lines, `duplicate` left out as a
  // duplicate of a line already saved for the same agency, or of the file's own (Third
  // Party GDS only; 0 elsewhere). `duplicate_of_*`: the earlier upload most of those are in.
  period_from?: string | null;
  period_to?: string | null;
  total_entries?: number;
  duplicate_entries?: number;
  new_entries?: number;
  duplicate_of_file?: string | null;
  duplicate_of_period?: string | null;
  /** Third Party GDS: its saved lines flagged as duplicates, by kind (backend
   *  services/tp_gds_reupload.py), and its tickets dated outside its period. */
  flags?: BatchFlags | null;
};
type BatchFlags = { exact: number; partial: number; in_file: number; outside: number };

/** A Third Party GDS line saved although it repeats one (`__dup__` on a served row). */
type DupInfo = { kind: "exact" | "partial" | "in_file"; fields: string[]; of_file: string | null; of_period: string | null };

const FLAG_CHIPS: { key: keyof BatchFlags; label: string; cls: string; title: string }[] = [
  { key: "partial", label: "partial", cls: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
    title: "Saved although an earlier statement of this agency has the same ticket & status with something changed" },
  { key: "in_file", label: "repeated", cls: "bg-indigo-50 text-indigo-700 border-indigo-200",
    title: "The same ticket & status appears more than once in this statement — every copy was saved" },
  { key: "exact", label: "saved again", cls: "bg-amber-50 text-amber-700 border-amber-200",
    title: "Already in an earlier statement of this agency, saved again by choice" },
  { key: "outside", label: "outside period", cls: "bg-rose-50 text-rose-700 border-rose-200",
    title: "Tickets whose Booked Date or Issue Date falls outside the statement period" },
];
type BatchBilling = {
  resolution_status: "none" | "resolved" | "projected";
  billable_rows: number;
  resolved_rows: number;
  unresolved_rows: number;
  /** NDC rows carrying a projected ticket — several can share one. */
  projected_rows: number;
  /** DISTINCT tickets in billing. Differs from projected_rows whenever an ancillary
   *  latched onto a flight line, which is the normal case. */
  projected_tickets: number;
  /** Ancillary rows with no ticket to attach to — real money awaiting a decision. */
  unlatched_rows: number;
};
// `kind: "money"` is set by the backend for amount columns so they right-align and format.
// `readonly` marks a value worked out from other columns (GDS SSR Amount / GST On SF): it is
// shown, never typed over — the edit goes to its parts.
type Column = { header: string; field: string; kind?: string; readonly?: boolean };
const editableCol = (c: Column) => !c.field.startsWith("__") && !c.readonly;
type Row = Record<string, string | number | null> & { id: number };

// Declared per statement type in the backend spec; absent for types that have no filters,
// in which case the toolbar and the slab below simply never render.
type FilterSpec = { field: string; label: string; type: "select" | "text" };
type Summary = {
  fields: { field: string; label: string }[];
  computed: Record<string, string>;
  declared: Record<string, string | null> | null;
  declared_comparable: boolean;
  declared_note: string | null;
  row_count: number;
  leg_count: number;
  /** Running-account statements only (Third Party GDS, MO): the file's own balance lines.
   *  Their net — closing − opening + payments — is what `declared.net_amount` carries. */
  balance?: {
    opening: string | null; closing: string | null; payments: string | null;
    opening_source: string | null;
  } | null;
};
/** Third-party statements: how this batch's SF / GST On SF compare with the agency's
 *  vendor service charge (backend services/statement_sf_check.py). */
type SfCheck = {
  issued: number; refunds: number; checked: number; mismatched: number;
  agreement: string | null; agency_linked: boolean;
};
/** Per-row verdict on one field the view renders. */
type CellCheck = { status: "ok" | "mismatch"; expected: string; note: string };

type RecordsResponse = {
  total: number; columns: Column[]; rows: Row[];
  filters?: FilterSpec[]; summary?: Summary; needs_reprocess?: boolean;
  sf_check?: SfCheck;
  /** Why re-processing is offered. Absent = the original per-sector-split reason;
   *  "stale_format" = the batch was parsed by an older column spec than the one running
   *  now, so fields the current parser extracts are missing from its rows. */
  reprocess_reason?: "stale_format";
  stale_rows?: number;
};

const fmtDate = formatUploadedAt;
function errMsg(e: unknown, fallback: string): string {
  const m = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return typeof m === "string" ? m : fallback;
}
/** Indian grouping for amounts; anything non-numeric is passed through untouched. */
function fmtMoney(v: string | number | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(String(v).replace(/,/g, ""));
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

/** XLS/CSV upload modal for one adjustment type. */
export function UploadModal({ apiBase, title, requiresAirlineId, requiresSupplier, onClose, onDone,
  initialFile = null, initialAgencyId = null }: {
  apiBase: string;
  title: string;
  /** LCC types only — their exports name no carrier, so the ID is mandatory here. */
  requiresAirlineId?: boolean;
  /** Third-party types only — the uploader must name the consolidator from their Agency
   *  Master. A consolidator statement doesn't say who sent it, and the B2B deal is matched
   *  against the answer. */
  requiresSupplier?: boolean;
  onClose: () => void;
  onDone: () => void;
  /** Email intake → Process: start with this attachment and the sender's agency. */
  initialFile?: File | null;
  initialAgencyId?: number | null;
}) {
  const [file, setFile] = useState<File | null>(initialFile);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [airlines, setAirlines] = useState<TenantAirlineOpt[]>([]);
  const [tenantAirlineIds, setTenantAirlineIds] = useState<number[]>([]);
  const [agency, setAgency] = useState<VendorAgency | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Opened from an email: pre-pick the sender's agency (third-party types).
  useEffect(() => {
    if (!requiresSupplier || initialAgencyId == null) return;
    loadVendorAgencies()
      .then((list) => { const a = list.find((x) => x.id === initialAgencyId); if (a) setAgency(a); })
      .catch(() => { /* the user picks it */ });
  }, [requiresSupplier, initialAgencyId]);

  // Only fetched for the types that ask for it — the other statement types share this
  // modal and would be making a call they never use.
  useEffect(() => {
    if (!requiresAirlineId) return;
    api.get<TenantAirlineOpt[]>("/tenant-airlines/", { params: { active: true } })
      .then((r) => setAirlines(r.data))
      .catch(() => toast.error("Failed to load your Airline Master."));
  }, [requiresAirlineId]);

  // Narrowed to the carrier already picked — the server refuses a mixed selection.
  const airlineChoices = sameAirlineOnly(airlines, tenantAirlineIds);

  const pick = (f: File | null) => {
    if (f && !/\.(xlsx|xls|csv)$/i.test(f.name)) { toast.error("Choose an .xlsx, .xls or .csv file."); return; }
    setFile(f);
  };
  const submit = async () => {
    if (!file) { notifyRequired("Choose an .xlsx, .xls or .csv file to import."); return; }
    if (requiresAirlineId && !tenantAirlineIds.length) {
      notifyRequired("Select the airline ID(s) this statement belongs to — the file itself doesn't say.");
      return;
    }
    const agencyBlocked = requiresSupplier ? agencyBlockReason(agency) : null;
    if (agencyBlocked) { notifyRequired(agencyBlocked); return; }
    setUploading(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      // Repeated field, one per id — how FastAPI reads a list from form data.
      for (const id of tenantAirlineIds) fd.append("tenant_airline_ids", String(id));
      // The supplier-master row the agency was copied from — see StatementAgencyField.
      if (requiresSupplier && agency?.supplier_id != null) fd.append("supplier_id", String(agency.supplier_id));
      if (requiresSupplier && agency) fd.append("agency_id", String(agency.id));
      const { data } = await api.post<{ inserted: number; matched_columns: number; source_rows?: number; leg_rows?: number }>(`${apiBase}/upload`, fd);
      // Sector-split types insert more rows than the file has lines — say so, or "imported
      // 518" against a 223-line file reads like a bug.
      const split = data.source_rows != null && data.leg_rows != null && data.leg_rows !== data.source_rows;
      toast.success(split
        ? `Imported ${data.source_rows} ${title} ticket line${data.source_rows === 1 ? "" : "s"} as ${data.leg_rows} sector rows.`
        : `Imported ${data.inserted} ${title} row${data.inserted === 1 ? "" : "s"}.`);
      // The API refuses a file below its minimum recognised-column threshold, but
      // it will happily accept one just above it — and then most columns land
      // empty. The count was already in the response and simply never shown.
      if (data.matched_columns != null && data.matched_columns < LOW_MATCH_WARNING) {
        toast(
          `Only ${data.matched_columns} column${data.matched_columns === 1 ? "" : "s"} were recognised — most fields will be blank. Check the file against the Template.`,
          { icon: "⚠️", duration: 7000 }
        );
      }
      onDone();
    } catch (e) { toast.error(errMsg(e, "Failed to import the file.")); }
    finally { setUploading(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-800">Upload {title} spreadsheet</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0] ?? null); }}
            onClick={() => !file && inputRef.current?.click()}
            className={`cursor-pointer flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center ${
              dragging ? "border-blue-500 bg-blue-50" : file ? "border-emerald-200 bg-emerald-50/40" : "border-slate-200 bg-slate-50/60 hover:border-slate-300"}`}
          >
            {file ? (
              <div className="w-full max-w-sm flex items-center gap-3 rounded-lg border border-emerald-200 bg-white p-3 shadow-sm">
                <div className="w-9 h-9 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0"><FileSpreadsheet className="w-5 h-5 text-emerald-600" /></div>
                <div className="min-w-0 flex-1 text-left"><p className="text-xs font-semibold text-slate-800 truncate" title={file.name}>{file.name}</p><p className="text-[11px] text-slate-500">{(file.size / 1024).toFixed(0)} KB</p></div>
                <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
                <button onClick={(e) => { e.stopPropagation(); setFile(null); }} className="p-1 text-slate-400 hover:text-red-500 shrink-0"><X className="w-4 h-4" /></button>
              </div>
            ) : (
              <>
                <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mb-3"><Upload className="w-6 h-6 text-blue-600" /></div>
                <p className="text-sm font-medium text-slate-700">Drop your {title} export here</p>
                <p className="text-xs text-slate-400 mt-0.5">or click to browse · .xlsx, .xls, .csv</p>
              </>
            )}
            <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          </div>

          {/* Airline — REQUIRED for the LCC types. Nothing in those exports identifies
              the carrier, so this selection is the only source of it. Several ids are
              normal: one statement usually covers more than one of the user's logins. */}
          {requiresAirlineId && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50/60 px-3.5 py-3">
              <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                Airline <span className="text-red-500">*</span>
              </label>
              <MultiSelectDropdown
                options={toOptions(airlineChoices.options)}
                selected={tenantAirlineIds}
                onChange={setTenantAirlineIds}
                disabled={airlines.length === 0}
                placeholder={airlines.length ? "Select your airline ID(s)…" : "No airline IDs yet"}
                emptyText="No matching ID"
              />
              {/* Say why the list is short, or the narrowing reads as data loss. */}
              {airlineChoices.lockedAirline ? (
                <p className="text-[11px] text-slate-400 mt-1.5">
                  Showing {airlineChoices.lockedAirline} IDs — a statement carries one carrier,
                  so clear the selection to pick a different airline.
                </p>
              ) : (
                <p className="text-[11px] text-slate-400 mt-1.5">
                  This export doesn&apos;t name the carrier, so pick the ID you gave it. Add every
                  ID this statement covers.
                </p>
              )}
              {airlines.length === 0 && (
                <p className="text-[11px] text-amber-600 mt-2">
                  Your Airline Master is empty. Add the airline under User Master → Airline Master first.
                </p>
              )}
            </div>
          )}

          {/* Agency — REQUIRED for the third-party types. A consolidator statement never
              names its sender (the file's own "Customer Name" column is YOU), so this is
              the only source of it — and it is what the incoming B2B deal is matched
              against, so the wrong pick would price the statement against the wrong deal.
              The values are rows in the user's own Agency Master. */}
          {requiresSupplier && (
            <StatementAgencyField value={agency} onChange={setAgency} className="mt-4"
              channel={channelForApiBase(apiBase)} />
          )}

          <p className="text-[11px] text-slate-400 mt-3">The original file is stored so you can download it later. Columns are matched by header name.</p>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-slate-100">
          <button onClick={onClose} className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
          <button onClick={submit} disabled={!file || uploading} className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />} Import
          </button>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, sub, accent }: { label: string; value: string; sub?: ReactNode; accent?: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`text-sm font-bold mt-0.5 tabular-nums ${accent ?? "text-slate-800"}`}>{value}</p>
      {sub && <p className="text-[10px] mt-0.5 tabular-nums text-slate-400">{sub}</p>}
    </div>
  );
}

/**
 * Totals for the whole filtered set, lifted out of the table body.
 *
 * Statements carry their own grand-total line, and it does not always agree with the
 * column it claims to total. Rather than pick a winner, both figures are shown: the
 * computed total on top, the vendor's declared figure beneath, and an amber tint when
 * they disagree.
 */
function SummarySlab({ summary }: { summary: Summary }) {
  const { fields, computed, declared, declared_comparable, declared_note, row_count, leg_count, balance } = summary;
  const split = leg_count > row_count;
  return (
    <div className="mb-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2">
        <Stat
          label={split ? "Tickets · Sectors" : "Rows"}
          value={split ? `${row_count.toLocaleString("en-IN")} · ${leg_count.toLocaleString("en-IN")}` : row_count.toLocaleString("en-IN")}
          sub={split ? "split by sector" : undefined}
        />
        {fields.map((f) => {
          const c = computed[f.field];
          const d = declared?.[f.field];
          const differs = declared_comparable && d != null && d !== "" &&
            Math.abs(Number(String(c).replace(/,/g, "")) - Number(String(d).replace(/,/g, ""))) > 0.005;
          return (
            <Stat key={f.field} label={f.label} value={fmtMoney(c)}
              accent={differs ? "text-amber-700" : undefined}
              sub={
                d == null || d === "" ? undefined
                  : declared_comparable
                    ? <span className={differs ? "text-amber-600" : "text-emerald-600"}>
                        {differs ? "≠" : "✓"} file {fmtMoney(d)}
                      </span>
                    : <span className="text-slate-300">file {fmtMoney(d)}</span>
              } />
          );
        })}
      </div>
      {declared_note && <p className="mt-1.5 text-[11px] text-amber-700">{declared_note}</p>}
      {balance && (balance.opening != null || balance.closing != null) && (
        <p className="mt-1.5 text-[11px] text-slate-500">
          Statement balance: opening {fmtMoney(balance.opening)}
          {balance.opening_source === "user" && <span className="text-slate-400"> (entered)</span>}
          {balance.payments != null && <> · less payments {fmtMoney(balance.payments)}</>}
          {" "}· closing {fmtMoney(balance.closing)}
          {balance.opening == null && (
            <span className="text-slate-400"> — the file printed no opening balance, so its net cannot be checked</span>
          )}
        </p>
      )}
      {declared && !declared_comparable && (
        <p className="mt-1.5 text-[11px] text-slate-400">
          Filters are active — these totals cover the filtered rows only, so they are not comparable to the file&apos;s own Total line.
        </p>
      )}
    </div>
  );
}

export default function AdjustmentStatementsView({
  apiBase, slug, title, requiresAirlineId, requiresSupplier, supportsMapping, capturesPeriod,
  supportsBilling, billingWorklist, exportsEntries, doneHint, checks, captureControls, uploadHref,
}: {
  apiBase: string; slug: string; title: string; blurb?: string;
  /** LCC types only — see lib/statements.ts. Drives the mandatory Airline picker in
   *  the upload modal and the AIRLINE column below; every other type is unaffected. */
  requiresAirlineId?: boolean;
  /** Third-party types only — see lib/statements.ts. Drives the mandatory consolidator
   *  picker in the upload wizard and the AGENCY column below. */
  requiresSupplier?: boolean;
  /** Upload goes through the map → review & edit → confirm wizard rather than the one-shot
   *  modal. Mirrors `supports_mapping` in the backend spec, which is what actually decides
   *  whether /extract and /confirm answer for this type. */
  supportsMapping?: boolean;
  /** Third Party GDS — see lib/statements.ts. PERIOD, and TOTAL / ALREADY UPLOADED / NEW in
   *  place of ENTRIES, below. */
  capturesPeriod?: boolean;
  /** NDC and Third Party API — see lib/statements.ts. Drives the BILLING column below and
   *  the worklist it opens. Every other type renders no column and makes no billing
   *  request. */
  supportsBilling?: boolean;
  /** Which of the two worklists to open. Only read when `supportsBilling`. */
  billingWorklist?: "ndc" | "tp-api";
  /** NDC and Third Party API — see lib/statements.ts. An ENTRIES total beside UPLOADS, and
   *  a Download entries action serving the rows as stored. Absent everywhere else, which
   *  renders neither. */
  exportsEntries?: boolean;
  /** One line on the wizard's success screen saying where the imported rows went. */
  doneHint?: string;
  /** Payment Module tabs only. Adds a CHECKS column — completeness, continuity and vendor
   *  checks per upload — read from `api` for statement type `slug`. Absent everywhere else,
   *  which makes no request and renders no column. */
  checks?: { api: string; slug: string };
  /** Payment Module tabs only. The upload wizard asks for optional expected records and
   *  net amount, and compares them on its done screen. */
  captureControls?: boolean;
  /** The upload's own page (lib/statements.ts `uploadPage`). Upload XLS goes there instead
   *  of opening the wizard as a popup over this list. */
  uploadHref?: string;
}) {
  const router = useRouter();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const startUpload = () => (uploadHref ? router.push(uploadHref) : setUploadOpen(true));
  const [deleteTarget, setDeleteTarget] = useState<Batch | null>(null);
  const [deleting, setDeleting] = useState(false);
  // batch_id of the entries export being built — a large upload takes a few seconds.
  const [exporting, setExporting] = useState<string | null>(null);
  const [selected, setSelected] = useState<Batch | null>(null);
  // The billing worklist is a third view, alongside the uploads list and the records
  // drill-in. Local state rather than a route, matching `selected` — and matching what
  // LccDetailedView does for the same screen.
  const [billingTarget, setBillingTarget] = useState<Batch | null>(null);
  const [checkResults, setCheckResults] = useState<Record<string, CheckResult>>({});
  const [checksTarget, setChecksTarget] = useState<string | null>(null);

  // drill-in records
  const [columns, setColumns] = useState<Column[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [rtotal, setRtotal] = useState(0);
  const [roffset, setRoffset] = useState(0);
  const [rloading, setRloading] = useState(false);

  // Opt-in extras — only ever populated for statement types whose spec declares them.
  const [filters, setFilters] = useState<FilterSpec[]>([]);
  const [fvals, setFvals] = useState<Record<string, string>>({});
  const [facets, setFacets] = useState<Record<string, string[]>>({});
  const [summary, setSummary] = useState<Summary | null>(null);
  const [sfCheck, setSfCheck] = useState<SfCheck | null>(null);
  // Row editing — third-party statements only (backend api/v1/statements.py::edit_record).
  // One row at a time: `draft` holds its cells as typed until Save sends the changed ones.
  const rowsEditable = apiBase.endsWith("/tp-gds") || apiBase.endsWith("/tp-lcc");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [savingRow, setSavingRow] = useState(false);
  const [needsReprocess, setNeedsReprocess] = useState(false);
  // Which of the two re-process paths this batch needs. `null` = the per-sector split;
  // "stale_format" = re-run the current column spec over the stored source rows.
  const [reprocessReason, setReprocessReason] = useState<"stale_format" | null>(null);
  const [reprocessing, setReprocessing] = useState(false);
  // Opening a batch should feel instant; only filter edits are worth debouncing.
  const skipDebounce = useRef(true);

  const hasFilters = Object.values(fvals).some(Boolean);
  const hasSelects = filters.some((f) => f.type === "select");
  // `row_count` is a live COUNT of stored entries (the server's list_batches), so the sum
  // is what the system holds — not a counter that could drift from it.
  const totalEntries = batches.reduce((s, b) => s + b.row_count, 0);
  // File · [Airline] · [Agency] · [Period] · Uploaded · Entries (or Total · Already uploaded ·
  // New · Flags) · [Checks] · [Billing] · Uploaded by · Actions.
  // Computed rather than a literal, so adding a column can't leave the empty-state row short.
  const batchCols = 5 + (requiresAirlineId ? 1 : 0) + (requiresSupplier ? 1 : 0)
                      + (capturesPeriod ? 4 : 0) + (checks ? 1 : 0) + (supportsBilling ? 1 : 0);
  const checksApi = checks?.api;
  const checksSlug = checks?.slug;

  const fetchBatches = useCallback(async () => {
    setLoading(true);
    try { const { data } = await api.get<Batch[]>(`${apiBase}/batches`); setBatches(data); }
    catch { toast.error(`Failed to load ${title} uploads.`); }
    finally { setLoading(false); }
  }, [apiBase, title]);

  useEffect(() => {
    setSelected(null); setFvals({}); setFilters([]); setFacets({}); setSummary(null);
    fetchBatches();
  }, [fetchBatches, slug]);

  // Every upload's checks in one request. Re-read whenever the list is — an upload or a
  // delete changes the previous-statement continuity of its neighbours too.
  const fetchChecks = useCallback(async () => {
    if (!checksApi || !checksSlug) return;
    try {
      const { data } = await api.get<Record<string, CheckResult>>(checksApi, { params: { slug: checksSlug } });
      setCheckResults(data);
    } catch {
      // The column shows a dash; the uploads list itself is unaffected.
    }
  }, [checksApi, checksSlug]);
  useEffect(() => { fetchChecks(); }, [fetchChecks, batches]);

  const startEdit = (r: Row) => {
    const d: Record<string, string> = {};
    for (const c of columns) if (editableCol(c)) d[c.field] = r[c.field] != null ? String(r[c.field]) : "";
    setDraft(d);
    setEditingId(Number(r.id));
  };
  const saveEdit = async (r: Row) => {
    // Only what changed goes up — an untouched cell must not be re-stamped as "edited".
    const changed: Record<string, string> = {};
    for (const [k, v] of Object.entries(draft)) {
      const before = r[k] != null ? String(r[k]) : "";
      if (v.trim() !== before.trim()) changed[k] = v;
    }
    if (!Object.keys(changed).length) { setEditingId(null); return; }
    setSavingRow(true);
    try {
      const { data } = await api.patch<Row>(`${apiBase}/records/${r.id}`, { fields: changed });
      setRows(prev => prev.map(x => x.id === r.id ? data : x));
      setEditingId(null);
      toast.success("Row updated. Re-run commission on this statement to price the change.");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg ?? "Couldn't save the row.");
    } finally { setSavingRow(false); }
  };

  const loadRecords = useCallback(async (batchId: string, offset: number) => {
    setRloading(true);
    try {
      const params: Record<string, string | number> = { batch_id: batchId, offset, limit: PAGE };
      for (const [k, v] of Object.entries(fvals)) if (v) params[`f.${k}`] = v;
      const { data } = await api.get<RecordsResponse>(`${apiBase}/records`, { params });
      setColumns(data.columns); setRows(data.rows); setRtotal(data.total); setRoffset(offset);
      setEditingId(null);   // a reload replaces the rows — an open edit has nothing left to save
      setFilters(data.filters ?? []); setSummary(data.summary ?? null);
      setSfCheck(data.sf_check ?? null);
      setNeedsReprocess(!!data.needs_reprocess);
      setReprocessReason(data.reprocess_reason ?? null);
    } catch { toast.error("Failed to load rows."); }
    finally { setRloading(false); }
  }, [apiBase, fvals]);

  // One effect covers both typing and dropdowns, and always returns to page 1 — a filtered
  // view paged to offset 300 would otherwise land on an empty page.
  useEffect(() => {
    if (!selected) return;
    const delay = skipDebounce.current ? 0 : 250;
    skipDebounce.current = false;
    const t = setTimeout(() => loadRecords(selected.batch_id, 0), delay);
    return () => clearTimeout(t);
  }, [selected, loadRecords]);

  // Facet values are per batch, not per filter, so the options don't disappear as you narrow.
  useEffect(() => {
    if (!selected || !hasSelects) return;
    api.get<Record<string, string[]>>(`${apiBase}/records/facets`, { params: { batch_id: selected.batch_id } })
      .then((r) => setFacets(r.data ?? {}))
      .catch(() => {});   // types without facets simply 404 — not an error worth surfacing
  }, [apiBase, selected, hasSelects]);

  const openBatch = (b: Batch) => { skipDebounce.current = true; setFvals({}); setSelected(b); };
  const closeBatch = () => { setSelected(null); setFvals({}); setFilters([]); setSummary(null); };
  const clearFilters = () => setFvals({});

  // Two different repairs behind one button, because to the user they are the same act:
  // "this upload was read by an older version of the code — read it again". `resplit`
  // re-derives per-sector legs; `reprocess` re-runs the current column spec over the
  // stored source rows. Which one applies is the backend's call, not a prop.
  const reprocess = async () => {
    if (!selected) return;
    setReprocessing(true);
    try {
      if (reprocessReason === "stale_format") {
        const { data } = await api.post<{ rows: number; reparsed: number; skipped_no_raw: number }>(
          `${apiBase}/batches/${selected.batch_id}/reprocess`);
        toast.success(
          `Re-read ${data.reparsed} row${data.reparsed === 1 ? "" : "s"} with the current column spec.`
          + (data.skipped_no_raw ? ` ${data.skipped_no_raw} had no stored source row and were left as they were.` : ""));
      } else {
        const { data } = await api.post<{ source_rows: number; leg_rows: number }>(
          `${apiBase}/batches/${selected.batch_id}/resplit`);
        toast.success(`Split ${data.source_rows} ticket line${data.source_rows === 1 ? "" : "s"} into ${data.leg_rows} sector rows.`);
      }
      await fetchBatches();
      await loadRecords(selected.batch_id, 0);
    } catch (e) { toast.error(errMsg(e, "Failed to re-process this upload.")); }
    finally { setReprocessing(false); }
  };

  const downloadFile = async (b: Batch) => {
    try { const { data } = await api.get<{ url: string }>(`${apiBase}/batches/${b.batch_id}/file-url`, { params: { inline: false } }); window.open(data.url, "_blank"); }
    catch { toast.error("No stored file for this upload."); }
  };

  // Built server-side from the STORED rows, never from the uploaded file: downloadFile
  // hands back what was uploaded, this hands back what the system holds, so the two can
  // be laid side by side. `filters` are the drill-in's, so it exports what is on screen.
  const exportEntries = async (b: Batch, filters: Record<string, string> = {}) => {
    setExporting(b.batch_id);
    try { await downloadEntries(apiBase, b.batch_id, b.source_file, filters); }
    catch (e) { toast.error((e as Error).message); }
    finally { setExporting(null); }
  };

  const previewFile = async (b: Batch) => {
    try {
      const { data } = await api.get<{ url: string }>(`${apiBase}/batches/${b.batch_id}/file-url`, { params: { inline: true } });
      const isExcel = /\.(xlsx|xls)$/i.test(b.source_file || "");
      const target = isExcel
        ? `https://view.officeapps.live.com/op/view.aspx?src=${encodeURIComponent(data.url)}`
        : data.url;   // CSV etc. render fine inline
      window.open(target, "_blank");
    } catch { toast.error("No stored file for this upload."); }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`${apiBase}/batches/${deleteTarget.batch_id}`);
      toast.success("Upload deleted.");
      setDeleteTarget(null);
      if (selected?.batch_id === deleteTarget.batch_id) setSelected(null);
      fetchBatches();
    } catch { toast.error("Failed to delete."); }
    finally { setDeleting(false); }
  };

  const downloadTemplate = async () => {
    try {
      const { data } = await api.get(`${apiBase}/template`, { responseType: "blob" });
      const url = URL.createObjectURL(data as Blob);
      const a = document.createElement("a"); a.href = url; a.download = `${slug}_template.xlsx`; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Failed to download template."); }
  };

  // ── Billing worklist ──────────────────────────────────────────────────────
  // A third view, alongside the uploads list and the drill-in below. Only ever reachable
  // for a type whose spec declares a billing flow, so the other seven spec-repo types
  // never render it and never call its endpoints.
  if (billingTarget && supportsBilling) {
    const worklistProps = {
      apiBase,
      batchId: billingTarget.batch_id,
      fileName: billingTarget.source_file,
      // "none" is the "Set up billing" case — the only one where opening the worklist is
      // allowed to run the matcher, since re-matching an upload already in billing could
      // silently re-point a row billing is using.
      resolutionStatus: billingTarget.billing?.resolution_status ?? "none",
      onBack: () => { setBillingTarget(null); fetchBatches(); },
      onChanged: fetchBatches,
    };
    // Two worklists, one switch, no default. Guessing would open NDC's screen — with its
    // Line column and its `?latch=` calls — against a tp-api batch that has neither.
    return billingWorklist === "tp-api"
      ? <TpApiBillingWorklist {...worklistProps} rowCount={billingTarget.row_count} />
      : <NdcBillingWorklist {...worklistProps} />;
  }

  // ── Drill-in: one upload's rows ───────────────────────────────────────────
  if (selected) {
    const start = rtotal === 0 ? 0 : roffset + 1;
    const end = Math.min(roffset + rows.length, rtotal);
    return (
      <div>
        <div className="flex items-center gap-2 mb-3">
          <button onClick={closeBatch} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-700"><ArrowLeft className="w-3.5 h-3.5" /> Back to uploads</button>
          <span className="text-slate-300">|</span>
          <h3 className="text-sm font-semibold text-slate-800 truncate max-w-[320px]" title={selected.source_file ?? undefined}>{title} · {selected.source_file || "upload"}</h3>
          <span className="text-[11px] text-slate-400">
            {/* the filtered count, not the batch's — those differ the moment you filter */}
            · {rtotal.toLocaleString("en-IN")} {rtotal === 1 ? "row" : "rows"}
            {hasFilters && <span className="text-amber-600"> (filtered from {selected.row_count.toLocaleString("en-IN")})</span>}
            {" "}· {fmtDate(selected.uploaded_at)}
          </span>
          {(selected.has_file || exportsEntries) && (
            <div className="ml-auto flex items-center gap-2">
              {selected.has_file && (
                <>
                  <button onClick={() => previewFile(selected)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-700 border border-blue-200 bg-blue-50 rounded-lg hover:bg-blue-100">
                    <Eye className="w-3.5 h-3.5" /> Preview
                  </button>
                  <button onClick={() => downloadFile(selected)} title="The file exactly as it was uploaded"
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50">
                    {/* "Original file" only beside Download entries — alone, Download is unambiguous. */}
                    <Download className="w-3.5 h-3.5" /> {exportsEntries ? "Original file" : "Download"}
                  </button>
                </>
              )}
              {/* The rows on screen, as stored — filtered when the grid is. */}
              {exportsEntries && (
                <button onClick={() => exportEntries(selected, fvals)} disabled={exporting === selected.batch_id || rtotal === 0}
                  title="Download the entries stored in the system for this upload (.xlsx)"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-700 border border-emerald-200 bg-emerald-50 rounded-lg hover:bg-emerald-100 disabled:opacity-50">
                  {exporting === selected.batch_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
                  {hasFilters ? `Download ${rtotal.toLocaleString("en-IN")} filtered entries` : "Download entries"}
                </button>
              )}
            </div>
          )}
        </div>
        {/* Third-party: the batch's service fee against the agency's agreed rate. */}
        {sfCheck && (
          <div className={`mb-3 rounded-lg border px-3 py-2 text-xs flex flex-wrap items-center gap-x-4 gap-y-1 ${
            sfCheck.mismatched ? "border-red-200 bg-red-50 text-red-700" : "border-slate-200 bg-slate-50 text-slate-600"}`}>
            <span>
              <span className="font-semibold">{sfCheck.issued}</span> issued ·{" "}
              <span className="font-semibold">{sfCheck.refunds}</span> cancelled → refund
            </span>
            {sfCheck.agreement ? (
              sfCheck.mismatched ? (
                <span className="font-semibold">
                  {sfCheck.mismatched} of {sfCheck.checked} issued ticket{sfCheck.checked !== 1 ? "s" : ""}{" "}charge a
                  service fee that doesn&apos;t match the agency&apos;s {sfCheck.agreement} — shown in red below.
                </span>
              ) : (
                <span>Service fee matches the agency&apos;s {sfCheck.agreement} on all {sfCheck.checked} checked tickets.</span>
              )
            ) : (
              <span className="text-slate-400">
                {sfCheck.agency_linked
                  ? "No vendor service charge on this agency's record — set it in Agency Master to check SF."
                  : "Uploaded before agencies were linked — the service fee isn't checked."}
              </span>
            )}
          </div>
        )}
        {needsReprocess && (
          <div className="flex items-center gap-2 mb-3 px-3 py-2.5 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800">
            <Split className="w-4 h-4 shrink-0" />
            <span>{reprocessReason === "stale_format"
              ? "This upload was read by an earlier version of the column spec, so columns the current one understands are blank below. Re-process it to read the stored file again — nothing is re-uploaded and the original rows are kept."
              : "This upload predates per-sector splitting. Re-process it to show one row per flown sector, with the fare and taxes divided across the legs, and to lift the file's Total line out of the table."}</span>
            <button onClick={reprocess} disabled={reprocessing}
              className="ml-auto shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-amber-600 rounded-lg hover:bg-amber-700 disabled:opacity-50">
              {reprocessing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Split className="w-3.5 h-3.5" />}
              {reprocessing ? "Re-processing…" : "Re-process"}
            </button>
          </div>
        )}

        {summary && <SummarySlab summary={summary} />}

        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          {filters.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap px-3 py-2.5 border-b border-slate-100 bg-slate-50/40">
              {filters.map((f) => (
                f.type === "select" ? (
                  <select key={f.field} value={fvals[f.field] ?? ""} className={SELECT_CLS}
                    onChange={(e) => setFvals((p) => ({ ...p, [f.field]: e.target.value }))}>
                    <option value="">All {f.label}</option>
                    {(facets[f.field] ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                ) : (
                  <div key={f.field} className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                    <input value={fvals[f.field] ?? ""} placeholder={f.label}
                      onChange={(e) => setFvals((p) => ({ ...p, [f.field]: e.target.value }))}
                      className="pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs w-36 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400" />
                  </div>
                )
              ))}
              {hasFilters && (
                <button onClick={clearFilters} className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800">
                  <X className="w-3.5 h-3.5" /> Clear
                </button>
              )}
              <span className="ml-auto text-[11px] text-slate-400">{rtotal.toLocaleString("en-IN")} rows</span>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="text-left border-collapse text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
                  {rowsEditable && <th className="px-2 py-2 sticky left-0 bg-slate-50 z-10" />}
                  {columns.map((c) => <th key={c.field} className={`px-3 py-2 font-semibold whitespace-nowrap ${c.kind === "money" ? "text-right" : ""}`}>{c.header}</th>)}
                </tr>
              </thead>
              <tbody>
                {rloading ? (
                  <tr><td colSpan={(columns.length || 1) + (rowsEditable ? 1 : 0)} className="px-3 py-8 text-center text-slate-400">Loading…</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={(columns.length || 1) + (rowsEditable ? 1 : 0)} className="px-3 py-8 text-center text-slate-400">
                    {hasFilters ? "No rows match these filters." : "No rows."}
                  </td></tr>
                ) : rows.map((r) => {
                  const legs = Number(r.__legs__ ?? 1);
                  return (
                  <tr key={r.id} className={`border-b border-slate-100 hover:bg-slate-50/60 ${legs > 1 ? "border-l-2 border-l-amber-200" : ""} ${editingId === r.id ? "bg-sky-50/60" : ""}`}>
                    {rowsEditable && (
                      <td className="px-2 py-1.5 whitespace-nowrap sticky left-0 bg-white z-10">
                        {editingId === r.id ? (
                          <span className="inline-flex gap-1">
                            <button onClick={() => saveEdit(r)} disabled={savingRow} title="Save"
                              className="p-1 rounded text-emerald-600 hover:bg-emerald-50 disabled:opacity-40">
                              {savingRow ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                            </button>
                            <button onClick={() => setEditingId(null)} disabled={savingRow} title="Cancel"
                              className="p-1 rounded text-slate-400 hover:bg-slate-100"><X className="w-3.5 h-3.5" /></button>
                          </span>
                        ) : (
                          <button onClick={() => startEdit(r)} disabled={editingId !== null} title="Edit this row"
                            className="p-1 rounded text-slate-400 hover:text-sky-600 hover:bg-sky-50 disabled:opacity-30">
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </td>
                    )}
                    {columns.map((c) => {
                      const v = r[c.field];
                      if (editingId === r.id && editableCol(c)) {
                        return <td key={c.field} className="px-1.5 py-1">
                          <input value={draft[c.field] ?? ""}
                            onChange={e => setDraft(d => ({ ...d, [c.field]: e.target.value }))}
                            onKeyDown={e => { if (e.key === "Enter") saveEdit(r); if (e.key === "Escape") setEditingId(null); }}
                            className={`w-full min-w-[90px] border border-sky-200 rounded px-1.5 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-sky-400 ${c.kind === "money" ? "text-right tabular-nums" : ""}`} />
                        </td>;
                      }
                      if (c.field === "__leg__") {
                        return <td key={c.field} className="px-3 py-1.5 text-xs whitespace-nowrap">
                          {legs > 1
                            ? <span className="inline-block px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-medium tabular-nums" title={`Sector ${v} of this ticket — fare and taxes divided across ${legs} legs`}>{String(v)}</span>
                            : <span className="text-slate-300">—</span>}
                        </td>;
                      }
                      const money = c.kind === "money";
                      const text = v != null && v !== "" ? (money ? fmtMoney(v) : String(v)) : null;
                      const check = (r.__checks__ as unknown as Record<string, CellCheck> | undefined)?.[c.field];
                      const bad = check?.status === "mismatch";
                      // Third Party GDS: a line saved although it repeats one, or dated outside
                      // its statement period — tagged beside its ticket number.
                      const dup = r.__dup__ as unknown as DupInfo | undefined;
                      const outside = r.__outside__ as unknown as Record<string, string> | undefined;
                      if (c.field === "ticket_number" && (dup || outside)) {
                        const from = dup?.of_file ? ` in ${dup.of_file}${dup.of_period ? ` (${dup.of_period})` : ""}` : "";
                        return <td key={c.field} className="px-3 py-1.5 text-xs whitespace-nowrap">
                          <span className="inline-flex items-center gap-1">
                            <span className="text-slate-700">{text ?? <span className="text-slate-300">—</span>}</span>
                            {dup && (
                              <span className={`px-1.5 py-0.5 rounded border text-[10px] font-semibold cursor-help ${
                                dup.kind === "partial" ? "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200"
                                  : dup.kind === "in_file" ? "bg-indigo-50 text-indigo-700 border-indigo-200"
                                  : "bg-amber-50 text-amber-700 border-amber-200"}`}
                                title={dup.kind === "partial"
                                  ? `Partial duplicate — the same ticket & status is saved${from || " in an earlier statement"}; ${dup.fields.join(", ") || "something"} changed. Saved by choice at upload.`
                                  : dup.kind === "in_file"
                                  ? `Repeated in this statement — the same ticket & status appears on an earlier line${dup.fields.length ? `, with ${dup.fields.join(", ")} different` : ""}.`
                                  : `Already saved${from || " in an earlier statement"} — saved again by choice at upload.`}>
                                {dup.kind === "partial" ? "Partial dup." : dup.kind === "in_file" ? "Repeated" : "Saved again"}
                              </span>
                            )}
                            {outside && (
                              <span className="px-1.5 py-0.5 rounded border bg-rose-50 text-rose-700 border-rose-200 text-[10px] font-semibold cursor-help"
                                title={Object.entries(outside).map(([f, s]) =>
                                  `${f === "booking_date" ? "Booked Date" : "Issue Date"} ${s} the statement period`).join(" · ")}>
                                Outside period
                              </span>
                            )}
                          </span>
                        </td>;
                      }
                      if (c.field === "ticket_status" && r.__kind__ === "refund") {
                        return <td key={c.field} className="px-3 py-1.5 text-xs whitespace-nowrap" title="Cancelled — reverses the issued ticket as a refund">
                          <span className="inline-flex items-center gap-1">
                            <span className="text-slate-700">{text}</span>
                            <span className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 text-[10px] font-semibold">Refund</span>
                          </span>
                        </td>;
                      }
                      return <td key={c.field}
                        className={`px-3 py-1.5 text-xs whitespace-nowrap max-w-[240px] truncate ${money ? "text-right tabular-nums" : ""} ${
                          bad ? "bg-red-50 text-red-700 font-semibold ring-1 ring-inset ring-red-200" : "text-slate-700"}`}
                        title={check ? check.note : (v != null ? String(v) : undefined)}>
                        {String(r.__edited__ ?? "").split(",").includes(c.field) && (
                          <span className="inline-block w-1.5 h-1.5 rounded-full bg-sky-500 mr-1 align-middle" title="Edited after upload" />
                        )}
                        {text ?? <span className="text-slate-300">—</span>}
                        {bad && <span className="block text-[10px] font-normal text-red-500">expected {check!.expected}</span>}
                      </td>;
                    })}
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rtotal > 0 && (
            <div className="flex items-center justify-between px-3 py-2.5 border-t border-slate-100 text-xs text-slate-500">
              <span>Showing {start}–{end} of {rtotal.toLocaleString()}</span>
              <div className="flex items-center gap-1">
                <button disabled={roffset === 0 || rloading} onClick={() => loadRecords(selected.batch_id, Math.max(0, roffset - PAGE))} className="flex items-center gap-1 px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40"><ChevronLeft className="w-3.5 h-3.5" /> Prev</button>
                <button disabled={roffset + PAGE >= rtotal || rloading} onClick={() => loadRecords(selected.batch_id, roffset + PAGE)} className="flex items-center gap-1 px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40">Next <ChevronRight className="w-3.5 h-3.5" /></button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Uploads (statement-type) list ─────────────────────────────────────────
  return (
    <div>
      <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="bg-white border border-slate-200 rounded-lg px-4 py-2">
            <span className="text-[10px] uppercase tracking-wide text-slate-400">Uploads</span>
            <span className="ml-2 text-sm font-bold text-slate-800">{batches.length}</span>
          </div>
          {/* Every upload counts: this router imports synchronously, so an upload is listed
              only once its rows are in — unlike LCC Detailed, nothing here is mid-import. */}
          {exportsEntries && (
            <div className="bg-white border border-slate-200 rounded-lg px-4 py-2"
              title={`Entries stored in the system across ${batches.length.toLocaleString()} ${batches.length === 1 ? "upload" : "uploads"}`}>
              <span className="text-[10px] uppercase tracking-wide text-slate-400">Entries</span>
              <span className="ml-2 text-sm font-bold text-slate-800 tabular-nums">{totalEntries.toLocaleString()}</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchBatches} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"><RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh</button>
          <button onClick={downloadTemplate} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"><Download className="w-3.5 h-3.5" /> Template</button>
          <button onClick={startUpload} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700"><Upload className="w-3.5 h-3.5" /> Upload XLS</button>
        </div>
      </div>

      {/* Scrolls sideways rather than clipping: with Period, the tally, Checks and Billing
          the table can be wider than the page, and a clipped one lost its Actions column with
          no way to reach it. Actions is pinned to the right edge so it is always in view. */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
              <th className="text-left px-3 py-2.5 font-semibold">File</th>
              {requiresAirlineId && <th className="text-left px-3 py-2.5 font-semibold">Airline</th>}
              {requiresSupplier && <th className="text-left px-3 py-2.5 font-semibold">Agency</th>}
              {capturesPeriod && <th className="text-left px-3 py-2.5 font-semibold" title="The days the statement covers, as declared at upload">Period</th>}
              <th className="text-left px-3 py-2.5 font-semibold">Uploaded</th>
              {capturesPeriod ? (
                <>
                  <th className="text-right px-3 py-2.5 font-semibold" title="Entries in the file — its OLD / BALANCE lines are not entries">Total</th>
                  <th className="text-right px-3 py-2.5 font-semibold" title="Left out at upload as duplicates of lines already saved for this agency (or of the file's own) — not counted twice">Already uploaded</th>
                  <th className="text-right px-3 py-2.5 font-semibold" title="Saved as this upload's own entries — duplicates saved by choice included, flagged">New</th>
                  <th className="text-left px-3 py-2.5 font-semibold" title="Saved lines to look at: partial duplicates, repeats within the file, lines saved again, and tickets dated outside the period">Flags</th>
                </>
              ) : (
                <th className="text-right px-3 py-2.5 font-semibold">Entries</th>
              )}
              {checks && <th className="text-left px-3 py-2.5 font-semibold">Checks</th>}
              {supportsBilling && <th className="text-left px-3 py-2.5 font-semibold">Billing</th>}
              <th className="text-left px-3 py-2.5 font-semibold">Uploaded by</th>
              <th className={`text-right px-3 py-2.5 font-semibold bg-slate-50 ${PINNED_RIGHT}`}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={batchCols} className="px-3 py-10 text-center text-slate-400">Loading…</td></tr>
            ) : batches.length === 0 ? (
              <tr><td colSpan={batchCols} className="px-3 py-12 text-center text-slate-400">No {title} uploads yet. <button onClick={startUpload} className="text-blue-600 hover:underline">Upload an XLS</button>.</td></tr>
            ) : batches.map((b) => (
              <tr key={b.batch_id} className="group border-b border-slate-100 hover:bg-slate-50">
                <td className="px-3 py-2">
                  <button onClick={() => openBatch(b)} className="flex items-center gap-2 text-slate-700 hover:text-blue-700">
                    <FolderOpen className="w-4 h-4 shrink-0 text-slate-400" />
                    <span className="font-medium truncate max-w-[240px]" title={b.source_file ?? undefined}>{b.source_file || "upload"}</span>
                  </button>
                </td>
                {requiresAirlineId && (
                  <td className="px-3 py-2 whitespace-nowrap">
                    {b.airline_name ? (
                      <span className="text-xs text-slate-700">
                        {b.airline_code && <span className="font-semibold">{b.airline_code}</span>} {b.airline_name}
                        {b.airline_ref_ids?.[0] && <span className="text-slate-400"> · {b.airline_ref_ids[0]}</span>}
                        {/* One upload can cover several ids; spelling them all out
                            would wreck the column, so count the rest. */}
                        {(b.airline_ref_ids?.length ?? 0) > 1 && (
                          <span
                            className="ml-1 text-[10px] font-semibold text-slate-500 bg-slate-100 border border-slate-200 rounded px-1 py-0.5"
                            title={`This upload covers ${b.airline_ref_ids!.length} IDs: ${b.airline_ref_ids!.join(", ")}`}
                          >
                            +{b.airline_ref_ids!.length - 1}
                          </span>
                        )}
                      </span>
                    ) : (
                      // Uploaded before the airline was captured. Nothing in the file
                      // says which carrier it was, so there is nothing to backfill.
                      <span className="text-xs text-slate-300" title="Uploaded before the airline was captured">—</span>
                    )}
                  </td>
                )}
                {requiresSupplier && (
                  <td className="px-3 py-2 whitespace-nowrap">
                    {b.supplier_name ? (
                      <span className="block text-xs leading-snug text-slate-700">
                        {b.supplier_name}
                        {/* Branch and code are what tell two rows of one vendor apart, so
                            they are shown, not just stored — on a line of their own, which
                            keeps the column narrow. */}
                        {(b.supplier_branch || b.supplier_code) && (
                          <span className="block text-[11px] text-slate-400">
                            {[b.supplier_branch, b.supplier_code].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </span>
                    ) : (
                      // Uploaded before the consolidator was captured. The file names no
                      // sender, so there is nothing to backfill — re-upload to attribute it.
                      <span className="text-xs text-slate-300" title="Uploaded before the consolidator was captured">—</span>
                    )}
                  </td>
                )}
                {capturesPeriod && (
                  <td className="px-3 py-2 text-xs whitespace-nowrap">
                    {b.period_from && b.period_to ? (
                      <span className="text-slate-700">{formatPeriod(b.period_from, b.period_to)}</span>
                    ) : (
                      // Uploaded before the period was asked for, and neither its file name
                      // nor its Week column said one — never compared with a re-upload.
                      <span className="text-slate-300" title="Uploaded before the statement period was captured">—</span>
                    )}
                  </td>
                )}
                <td className="px-3 py-2 text-xs text-slate-500 whitespace-nowrap" title={fmtDate(b.uploaded_at)}>
                  {(() => {
                    const at = uploadedAtParts(b.uploaded_at);
                    return at
                      ? <><span className="block">{at.date}</span><span className="block text-[11px] text-slate-400">{at.time}</span></>
                      : fmtDate(b.uploaded_at);
                  })()}
                </td>
                {capturesPeriod ? (
                  <>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-700">{(b.total_entries ?? b.row_count).toLocaleString()}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {b.duplicate_entries ? (
                        <span className="font-medium text-amber-700 cursor-help"
                          title={`Left out as duplicates${b.duplicate_of_file ? ` — mostly of lines in ${b.duplicate_of_file}` : ""}${b.duplicate_of_period ? ` (${b.duplicate_of_period})` : ""}; not counted twice`}>
                          {b.duplicate_entries.toLocaleString()}
                        </span>
                      ) : <span className="text-slate-300">0</span>}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-700">{(b.new_entries ?? b.row_count).toLocaleString()}</td>
                    <td className="px-3 py-2">
                      {b.flags && FLAG_CHIPS.some((f) => b.flags![f.key] > 0) ? (
                        <span className="flex flex-wrap gap-1">
                          {FLAG_CHIPS.filter((f) => b.flags![f.key] > 0).map((f) => (
                            <span key={f.key} title={f.title}
                              className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-semibold cursor-help ${f.cls}`}>
                              {b.flags![f.key].toLocaleString()} {f.label}
                            </span>
                          ))}
                        </span>
                      ) : <span className="text-xs text-slate-300">—</span>}
                    </td>
                  </>
                ) : (
                  <td className="px-3 py-2 text-right tabular-nums text-slate-700">{b.row_count.toLocaleString()}</td>
                )}
                {checks && (
                  <td className="px-3 py-2">
                    <ChecksBadge result={checkResults[b.batch_id]} onOpen={() => setChecksTarget(b.batch_id)} />
                  </td>
                )}
                {supportsBilling && (
                  <td className="px-3 py-2 whitespace-nowrap">
                    {/* No "still importing" branch, unlike LccDetailedView's version of
                        this cell: this router ingests synchronously, so a batch exists
                        only once its rows are in. */}
                    {!b.billing || b.billing.resolution_status === "none" ? (
                      <button onClick={() => setBillingTarget(b)}
                        className="text-[11px] font-medium text-blue-600 hover:underline">
                        Set up billing
                      </button>
                    ) : (
                      <button onClick={() => setBillingTarget(b)} className="text-left group">
                        <span className="text-[11px] tabular-nums text-slate-700 group-hover:underline">
                          {b.billing.billable_rows === 0
                            ? <span className="text-amber-600">nothing here can be billed</span>
                            : <>{b.billing.resolved_rows.toLocaleString()} / {b.billing.billable_rows.toLocaleString()} billable</>}
                        </span>
                        <span className="block text-[10px]">
                          {b.billing.projected_tickets > 0
                            ? <span className="text-emerald-600">
                                {b.billing.projected_tickets.toLocaleString()} ticket{b.billing.projected_tickets === 1 ? "" : "s"} in billing
                              </span>
                            : <span className="text-amber-600">not sent to billing yet</span>}
                          {b.billing.unlatched_rows > 0 && (
                            <span className="text-amber-600" title="Ancillary rows with no ticket to attach to">
                              {" · "}{b.billing.unlatched_rows} unattached
                            </span>
                          )}
                          {/* tp-api has no latching, but a multi-product file rarely bills every
                              line: pending payments, fully refunded cancellations and rows with
                              no billing category stay out. Saying nothing here would let "1
                              ticket in billing" read as "all of it". `row_count - billable_rows`
                              is the excluded count — NOT `billable_rows - resolved_rows`, which
                              is "billable but has no party yet". */}
                          {billingWorklist === "tp-api" && b.row_count > b.billing.billable_rows && (
                            <span className="text-slate-500"
                              title="Pending payments, cancellations with nothing to bill, refunds to review and rows with no billing category stay on the statement. An upload classified before every category billed needs a Re-match. Open Billing to see each reason.">
                              {" · "}{(b.row_count - b.billing.billable_rows).toLocaleString()} of {b.row_count.toLocaleString()} not billable
                            </span>
                          )}
                        </span>
                      </button>
                    )}
                  </td>
                )}
                <td className="px-3 py-2 text-xs text-slate-500">{b.created_by_name || "—"}</td>
                <td className={`px-3 py-2 text-right whitespace-nowrap bg-white group-hover:bg-slate-50 ${PINNED_RIGHT}`}>
                  <button onClick={() => openBatch(b)} className="text-xs font-medium text-blue-600 hover:underline mr-3">Open</button>
                  {b.has_file && <button onClick={() => previewFile(b)} className="p-1 text-slate-400 hover:text-blue-600 mr-1" title="Preview file"><Eye className="w-3.5 h-3.5" /></button>}
                  {b.has_file && <button onClick={() => downloadFile(b)} className="p-1 text-slate-400 hover:text-slate-700 mr-1" title="Download the original file, as uploaded"><Download className="w-3.5 h-3.5" /></button>}
                  {exportsEntries && (
                    <button onClick={() => exportEntries(b)} disabled={exporting === b.batch_id}
                      className="p-1 text-slate-400 hover:text-emerald-600 mr-1 disabled:opacity-50"
                      title="Download the entries stored in the system (.xlsx)">
                      {exporting === b.batch_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
                    </button>
                  )}
                  <button onClick={() => setDeleteTarget(b)} className="p-1 text-slate-400 hover:text-red-600" title="Delete upload"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      {/* The types with no single fixed export get the map -> review -> confirm wizard: a
          consolidator writes whatever spreadsheet it likes, and every airline runs its own
          NDC portal with its own header names. The rest come out of one system with one
          export (BSPlink, a GDS), where a mapping step would be a question with one
          possible answer — those keep the one-shot modal. `supportsMapping` mirrors the
          backend spec, which is what actually decides whether /extract and /confirm exist. */}
      {uploadOpen && (supportsMapping
        ? <StatementUploadWizard
            apiBase={apiBase} title={title} requireSupplier={requiresSupplier}
            doneHint={doneHint} captureControls={captureControls}
            onClose={() => setUploadOpen(false)}
            onDone={() => { setUploadOpen(false); fetchBatches(); }} />
        : <UploadModal apiBase={apiBase} title={title} requiresAirlineId={requiresAirlineId} requiresSupplier={requiresSupplier} onClose={() => setUploadOpen(false)} onDone={() => { setUploadOpen(false); fetchBatches(); }} />)}

      {checksApi && checksTarget && checkResults[checksTarget] && (
        <ChecksPanel key={checksTarget} api={checksApi} result={checkResults[checksTarget]}
          onClose={() => setChecksTarget(null)} onChanged={fetchChecks} />
      )}

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
            <div className="flex items-center gap-2.5 mb-2"><AlertTriangle className="w-5 h-5 text-red-500" /><h2 className="text-sm font-semibold text-slate-800">Delete this upload?</h2></div>
            <p className="text-xs text-slate-500 mb-4">This permanently removes all {deleteTarget.row_count} row{deleteTarget.row_count === 1 ? "" : "s"} from “{deleteTarget.source_file || "upload"}”. This cannot be undone.</p>
            {/* Third Party GDS: a later upload of this agency that left out entries as already
                saved — whatever its period — may hold only what was new to it, so deleting this
                one can leave those entries saved nowhere until that statement is re-uploaded. */}
            {capturesPeriod && (() => {
              const others = batches.filter((o) => o.batch_id !== deleteTarget.batch_id
                && o.agency_id != null && o.agency_id === deleteTarget.agency_id
                && (o.duplicate_entries ?? 0) > 0 && o.uploaded_at > deleteTarget.uploaded_at);
              if (!others.length) return null;
              return (
                <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  {others.map((o) => `${o.source_file || "Another upload"} (${formatPeriod(o.period_from, o.period_to)}, ${fmtDate(o.uploaded_at)})`).join(", ")}
                  {" "}left out entries already saved for this agency — some may be in this one. After deleting it,
                  upload {others.length === 1 ? "that statement" : "those statements"} again to bring them back.
                </div>
              );
            })()}
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeleteTarget(null)} className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
              <button onClick={confirmDelete} disabled={deleting} className="px-4 py-1.5 text-xs font-semibold text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50">{deleting ? "Deleting…" : "Delete"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
