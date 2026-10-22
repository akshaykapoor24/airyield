"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload, CheckCircle, AlertCircle, RefreshCw, ChevronLeft,
  FileSpreadsheet, X, Download, ArrowRight, ChevronDown, Trash2, Plus, Search,
  FileText, CopyX, CalendarDays,
} from "lucide-react";
import api from "@/lib/api";
import { useStatementSectionBase } from "@/lib/statementSection";
import StatementFormPanel, { isStatementComplete as statementComplete, type StatementType } from "@/components/tickets/StatementFormPanel";
import CustomerPartyPanel, { type FieldHint } from "@/components/statements/CustomerPartyPanel";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import {
  CUSTOMER_TYPE_LABEL, EMPTY_TAG, buildTagPayload, isTagComplete, type CustomerTag, type CustomerType,
} from "@/lib/customerType";
import { formatDay, formatPeriod, formatUploadedAt } from "@/lib/statementPeriod";
import {
  type DateField, type DateFormats, type DateOrder, type DatesRead, type DetectedFormat,
  DateFormatSection, DatesReadList, orderLabel, useDateFormats,
} from "@/components/statements/dateFormat";

/** Internal Statement's declared date columns — backend services/ticket_extraction.py
 *  DATE_FORMAT_FIELDS. Doc Date follows the Ticket Date there. */
const TICKET_DATE_FIELDS: DateField[] = [
  { field: "ticket_date", header: "Ticket Date" },
  { field: "departure_datetime", header: "Travel Date" },
];
const NO_DATE_FIELDS: DateField[] = [];
const ISO_DAY = /^\d{4}-\d{2}-\d{2}/;

type AgencyOpt = { id: number; name: string; branch_name: string | null; branch_code: string; channels: string };

/** "Lords Travels — Delhi · GDS".
 *
 *  BRANCH AND CHANNEL BOTH BELONG IN THE LABEL. A vendor is onboarded once per
 *  branch and once per channel, and each is a separate account with its own
 *  balance. `selectedAgency` below matches on this string, so a label that
 *  stopped at the branch would render Lords Delhi GDS and Lords Delhi LCC
 *  identically and file the statement under whichever came back first. */
const agencyOptionLabel = (a: AgencyOpt) =>
  `${a.name} — ${a.branch_name || a.branch_code} · ${a.channels}`;
import {
  mappingFieldsFor, reviewColGroups,
  type ReviewColGroup as TColGroup,
  type TicketRow, type TicketExtractionPreview as ExtractionPreview,
} from "@/lib/ticketFields";

import { useRouter } from "next/navigation";
import Link from "next/link";

// Field metadata lives in @/lib/ticketFields so the mapping step, the review
// grid, the manual punch form and the edit modal cannot drift apart.
const TICKET_COL_GROUPS: TColGroup[] = reviewColGroups();

// Agency options are fetched live from the supplier master API

const SKIP = "__skip__";

// ── Internal Statement: what the attached file says about itself ─────────────────
// Backend: api/v1/internal_tickets.py (/upload/guess) and services/statement_party.py.
type GuessPeriod = { from: string; to: string; label: string; source: string };
type PartyCandidate = { customer_type: CustomerType; id: number; name: string };
type GuessResp = {
  period: GuessPeriod | null;
  /** The header line's period, only when it says something other than the file name. */
  header_period: GuessPeriod | null;
  party: {
    status: "resolved" | "ambiguous" | "unresolved";
    customer_type: CustomerType | null; id: number | null; name: string | null;
    candidates: PartyCandidate[]; source: string | null;
    narrowed_by: "previous upload" | "branch" | null; matched: string | null;
  };
};

// ── Internal Statement: tickets already loaded ───────────────────────────────────
// Backend: api/v1/internal_tickets.py (/upload/duplicates) and services/ticket_duplicates.py.
// A row is a duplicate when its Booked Date, Ticket No, Pax Name, Amount and Travel Date match
// a ticket already loaded — any uploaded statement or Create Ticket entry, of any period. Not
// saved. The file is not checked against itself: a row it holds twice is saved twice.
/** A statement some of the file's tickets are already loaded in. */
type LoadedStatement = {
  batch_id: string; statement_name: string | null; file_name: string | null;
  period_label: string; uploaded_at: string | null;
  /** This file's duplicates already loaded in it. */
  matched: number;
};
type DuplicateLine = {
  doc_no: string | null; ticket_number: string | null; pax_name: string | null;
  booked_date: string | null; travel_date: string | null; total_amt: number | string | null;
  index: number;
  /** The statement it is already loaded in. */
  batch_id: string;
};
type DuplicateReport = {
  total: number; duplicates: number; duplicates_amount: string; new: number;
  statements: LoadedStatement[];
  lines: DuplicateLine[];                              // the first 200
};
type DuplicateCheck = DuplicateReport & {
  rows: { index: number; batch_id: string }[];   // every one, for the grid
  can_save: boolean;
  reason: string | null;
};

function apiDetail(e: unknown): string | null {
  const m = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return typeof m === "string" ? m : null;
}

const fmtMoney = (v: number | string | null | undefined) =>
  v == null || v === "" ? "—" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 });

/** Where a duplicate's ticket is already loaded. */
function duplicateOf(d: { batch_id: string }, statements: LoadedStatement[]): string {
  const s = statements.find(x => x.batch_id === d.batch_id);
  if (!s) return "An earlier statement";
  return `${s.statement_name ?? s.file_name ?? "A statement"} · ${s.period_label} · uploaded ${formatUploadedAt(s.uploaded_at)}`;
}

/** The duplicates of a file, and where each ticket already is. */
function DuplicateTickets({ check }: { check: DuplicateCheck }) {
  return (
    <div className="mt-2 max-h-56 overflow-auto border border-gray-200 rounded-lg bg-white">
      <table className="w-full text-[11px] text-left">
        <thead className="bg-gray-50 text-gray-500 sticky top-0">
          <tr>
            <th className="px-2 py-1 font-medium">Row</th>
            <th className="px-2 py-1 font-medium">Ticket No</th>
            <th className="px-2 py-1 font-medium">Pax Name</th>
            <th className="px-2 py-1 font-medium">Booked Date</th>
            <th className="px-2 py-1 font-medium">Travel Date</th>
            <th className="px-2 py-1 font-medium text-right">Amount</th>
            <th className="px-2 py-1 font-medium">Already in</th>
          </tr>
        </thead>
        <tbody>
          {check.lines.map((d, i) => (
            <tr key={i} className="border-t border-gray-100 text-gray-700">
              <td className="px-2 py-1 text-gray-400 tabular-nums">{d.index + 1}</td>
              <td className="px-2 py-1 font-mono">{d.ticket_number ?? "—"}</td>
              <td className="px-2 py-1">{d.pax_name ?? "—"}</td>
              <td className="px-2 py-1 whitespace-nowrap">{formatDay(d.booked_date)}</td>
              <td className="px-2 py-1 whitespace-nowrap">{formatDay(d.travel_date)}</td>
              <td className="px-2 py-1 text-right tabular-nums">{fmtMoney(d.total_amt)}</td>
              <td className="px-2 py-1 text-gray-500">{duplicateOf(d, check.statements)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The preview's answer to "are any of these tickets already loaded?" — said here, before
 *  Save, not as an error after it. Duplicates are left out; the rest are saved. */
function DuplicateBox({ check, busy, error, onlyShown, onToggleOnly }: {
  check: DuplicateCheck | null; busy: boolean; error: string | null;
  onlyShown: boolean; onToggleOnly: () => void;
}) {
  const [show, setShow] = useState(false);
  if (error) {
    return (
      <div className="flex items-start gap-2 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-800">
        <AlertCircle className="w-4 h-4 shrink-0 mt-px" /><span>{error}</span>
      </div>
    );
  }
  if (!check) {
    return busy ? (
      <div className="flex items-center gap-2 px-4 py-3 bg-white border border-gray-200 rounded-xl text-xs text-gray-500">
        <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Checking these tickets for duplicates…
      </div>
    ) : null;
  }
  if (check.duplicates === 0) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 bg-green-50 border border-green-200 rounded-xl text-xs text-green-800">
        <CheckCircle className="w-4 h-4 shrink-0 text-green-600" />
        No duplicates — none of these {check.total.toLocaleString("en-IN")} tickets is loaded yet, so all of them
        will be saved.
        {busy && <RefreshCw className="w-3.5 h-3.5 animate-spin text-green-500" />}
      </div>
    );
  }
  const blocked = !check.can_save;
  const n = check.duplicates;
  return (
    <div className={`px-4 py-3 border rounded-xl text-xs ${blocked ? "bg-red-50 border-red-200" : "bg-amber-50 border-amber-200"}`}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-gray-600">
        <span className="flex items-center gap-1.5 font-semibold text-gray-800">
          <CopyX className={`w-4 h-4 ${blocked ? "text-red-500" : "text-amber-600"}`} /> Duplicate tickets
        </span>
        <span>Tickets in this file <strong className="text-sm text-gray-800">{check.total.toLocaleString("en-IN")}</strong></span>
        <span>Duplicates <strong className="text-sm text-amber-700">{n.toLocaleString("en-IN")}</strong></span>
        <span>New <strong className={`text-sm ${check.new ? "text-green-700" : "text-red-700"}`}>{check.new.toLocaleString("en-IN")}</strong></span>
        {busy && <RefreshCw className="w-3.5 h-3.5 animate-spin text-gray-400" />}
      </div>
      <p className={`mt-1.5 ${blocked ? "text-red-700" : "text-gray-700"}`}>
        {blocked ? (
          <><strong>This statement will not be saved.</strong> {check.reason}</>
        ) : (
          <>The {n.toLocaleString("en-IN")} duplicate{n === 1 ? " is" : "s are"} ignored (marked below) — the{" "}
            {check.new.toLocaleString("en-IN")} new ticket{check.new === 1 ? "" : "s"} will be saved.</>
        )}{" "}
        A ticket is a duplicate when its Booked Date, Ticket No, Pax Name, Amount and Travel Date match a ticket
        already loaded — from any statement you uploaded or any ticket you created.
        <span className="block mt-1.5 space-x-3">
          <button onClick={() => setShow(v => !v)} className="text-blue-600 hover:underline font-medium">
            {show ? "Hide" : "Show"} the duplicates
          </button>
          <button onClick={onToggleOnly} className="text-blue-600 hover:underline font-medium">
            {onlyShown ? "Show every row in the grid" : "Show only the duplicates in the grid"}
          </button>
        </span>
      </p>
      {check.statements.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-gray-500">
          {check.statements.map(s => (
            <li key={s.batch_id}>
              <strong className="text-gray-700">{s.matched.toLocaleString("en-IN")}</strong> already loaded in{" "}
              <strong className="text-gray-700">{s.statement_name ?? "a statement"}</strong> ({s.period_label}
              {s.file_name ? ` · ${s.file_name}` : ""} · uploaded {formatUploadedAt(s.uploaded_at)})
            </li>
          ))}
        </ul>
      )}
      {show && <DuplicateTickets check={check} />}
      {show && check.lines.length < n && (
        <p className="text-[11px] text-gray-500 mt-1">Showing the first {check.lines.length}.</p>
      )}
    </div>
  );
}

// ── Editable review table ──────────────────────────────────────────────────
function TicketReviewTable({
  rows, colGroups, onChange, onDelete, onAdd,
  filterText, selectedRows, onToggleRow, onToggleAllFiltered, duplicateIn, onlyRows,
}:{
  rows: TicketRow[];
  colGroups: TColGroup[];
  onChange: (idx: number, key: string, val: string) => void;
  onDelete: (idx: number) => void;
  onAdd: () => void;
  filterText: string;
  selectedRows: Set<number>;
  onToggleRow: (idx: number) => void;
  onToggleAllFiltered: (filteredIndices: number[], allSelected: boolean) => void;
  /** Internal Statement: duplicate rows → where the ticket already is. Greyed, not saved. */
  duplicateIn?: Map<number, string>;
  /** Only these rows ("Show only the duplicates in the grid"); every row when null. */
  onlyRows?: Set<number> | null;
}) {
  const allCols = colGroups.flatMap(g => g.cols);
  const inp = "w-full bg-transparent text-[11px] text-gray-800 focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5 min-w-[72px]";

  const filteredIndices: number[] = rows.reduce<number[]>((acc, row, i) => {
    if (onlyRows && !onlyRows.has(i)) return acc;
    if (!filterText) { acc.push(i); return acc; }
    const haystack = Object.values(row).filter(v => v != null).join(" ").toLowerCase();
    if (haystack.includes(filterText.toLowerCase())) acc.push(i);
    return acc;
  }, []);
  const allFilteredSelected = filteredIndices.length > 0 && filteredIndices.every(i => selectedRows.has(i));
  const someFilteredSelected = filteredIndices.some(i => selectedRows.has(i));

  return (
    <div className="overflow-x-auto border border-gray-200 rounded-lg">
      <table className="w-full min-w-max border-collapse">
        <thead>
          <tr>
            <th className="px-2 py-2 sticky left-0 z-10" style={{background:"#1e3a5f"}}>
              <input
                type="checkbox"
                checked={allFilteredSelected}
                ref={el=>{if(el)el.indeterminate=!allFilteredSelected&&someFilteredSelected;}}
                onChange={()=>onToggleAllFiltered(filteredIndices,allFilteredSelected)}
                className="accent-blue-400 cursor-pointer"
                title={allFilteredSelected?"Deselect all visible":"Select all visible"}
              />
            </th>
            <th className="px-2 py-2 text-[10px] text-white font-bold sticky left-9 z-10 whitespace-nowrap" style={{background:"#1e3a5f"}}>#</th>
            <th rowSpan={2} className="px-2 py-2 text-[10px] text-white font-bold uppercase tracking-wider text-center border-l border-white/20 whitespace-nowrap" style={{background:"#1e3a5f"}}>Type</th>
            {colGroups.map(g=>(
              <th key={g.label} colSpan={g.cols.length} className="px-2 py-2 text-[10px] text-white font-bold uppercase tracking-wider text-center border-l border-white/20 whitespace-nowrap" style={{background:g.color}}>
                {g.label}
              </th>
            ))}
            <th className="px-2 py-2" style={{background:"#1e3a5f"}}/>
          </tr>
          <tr style={{background:"#2d4f7c"}}>
            <th className="px-2 py-1.5 sticky left-0 z-10" style={{background:"#2d4f7c"}}/>
            <th className="px-2 py-1.5 sticky left-9 z-10" style={{background:"#2d4f7c"}}/>
            {allCols.map(c=>(
              <th key={c.key} className="px-2 py-1.5 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{c.label}</th>
            ))}
            <th className="px-2 py-1.5"/>
          </tr>
        </thead>
        <tbody>
          {filteredIndices.length===0?(
            <tr><td colSpan={allCols.length+4} className="px-4 py-10 text-center text-xs text-gray-400">
              {rows.length===0?"No rows. Add a row manually.":"No rows match the filter."}
            </td></tr>
          ):filteredIndices.map(idx=>{
            const row=rows[idx];
            const isSelected=selectedRows.has(idx);
            const duplicate=duplicateIn?.get(idx);
            return(
              <tr key={idx} title={duplicate?`Duplicate — already in ${duplicate}. Not saved.`:undefined}
                className={`border-b border-gray-100 group ${isSelected?"bg-blue-50":duplicate?"bg-gray-50 text-gray-400 opacity-60":"hover:bg-blue-50/20"}`}>
                <td className={`px-2 py-1.5 sticky left-0 ${isSelected?"bg-blue-50":"bg-white group-hover:bg-blue-50/20"}`}>
                  <input type="checkbox" checked={isSelected} onChange={()=>onToggleRow(idx)} className="accent-blue-500 cursor-pointer"/>
                </td>
                <td className={`px-2 py-1.5 text-[10px] text-gray-400 sticky left-9 ${isSelected?"bg-blue-50":"bg-white group-hover:bg-blue-50/20"}`}>{idx+1}</td>
                <td className="px-2 py-1.5 border-l border-gray-100 whitespace-nowrap">
                  {duplicate ? (
                    <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-700 border border-amber-200">Duplicate</span>
                  ) : row.split_type === "split"
                    ? <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-600 border border-amber-200">Split</span>
                    : <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-500">Normal</span>}
                </td>
                {allCols.map(col=>{
                  const raw=row[col.key as keyof TicketRow];
                  const val=raw==null?"":String(raw);
                  return(
                    <td key={col.key} className="px-1 py-1 border-l border-gray-100">
                      {col.type==="date"?(
                        <input type="date" className={inp} value={val} onChange={e=>onChange(idx,col.key,e.target.value)} onClick={e=>{try{(e.target as HTMLInputElement).showPicker()}catch{}}}/>
                      ):col.type==="number"?(
                        <input type="number" className={inp} value={val} onChange={e=>onChange(idx,col.key,e.target.value)} placeholder="—"/>
                      ):(
                        <input type="text" className={inp} value={val} onChange={e=>onChange(idx,col.key,e.target.value)} placeholder="—"/>
                      )}
                    </td>
                  );
                })}
                <td className="px-2 py-1.5">
                  <button onClick={()=>onDelete(idx)} className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded text-red-400">
                    <Trash2 className="w-3.5 h-3.5"/>
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="px-4 py-2.5 border-t border-gray-100">
        <button onClick={onAdd} className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline">
          <Plus className="w-3.5 h-3.5"/> Add row manually
        </button>
      </div>
    </div>
  );
}

// ── component ──────────────────────────────────────────────────────────────
/**
 * Upload Statement, in two modes.
 *
 *   "internal" — Internal Statement. Asks for a statement TYPE (B2B/AIRLINE) and
 *                the vendor agency the file came from. Unchanged.
 *   "customer" — Customer data → Statement. Asks WHO the tickets were sold to,
 *                and writes that tag to the DB for the commission run. There is
 *                no airline option here: an airline is a vendor, not a customer.
 *
 * One flow rather than two copies, so the wizard, the column mapping and the
 * review grid can never drift apart between the two entry points.
 */
export default function UploadTicketsPage({
  mode = "internal", apiBase = "/tickets", listHref, duplicateCheck = false, fillFromFile = false,
  askDateFormats = false,
}: {
  mode?: "internal" | "customer";
  /** "/internal-tickets" on Internal Statement — its own tables. */
  apiBase?: string;
  /** Where "view statements" goes after a save; the section's list by default. */
  listHref?: string;
  /** Internal Statement: the preview shows which rows are duplicates of a ticket already
   *  loaded (any period, any time) or of a row above them — only the rest are saved
   *  (`${apiBase}/upload/duplicates`; backend services/ticket_duplicates.py). */
  duplicateCheck?: boolean;
  /** Internal Statement: an attached file fills the statement details in — the customer, the
   *  period and the name, from its name and header lines — and the upload step waits for
   *  Next, so they are checked before the columns are mapped. */
  fillFromFile?: boolean;
  /** Internal Statement: ask how the sheet writes its Ticket Date and Travel Date — filled in
   *  from the file, else the customer's last statement — and read every date that way
   *  (components/statements/dateFormat.tsx; backend services/ticket_extraction.py). */
  askDateFormats?: boolean;
} = {}) {
  const isCustomer = mode === "customer";
  const sectionBase = useStatementSectionBase();
  const router = useRouter();

  type Step = "drop" | "mapping" | "preview" | "saving" | "done";
  const [step,           setStep]           = useState<Step>("drop");
  const [preview,        setPreview]        = useState<ExtractionPreview | null>(null);
  const [storedFile,     setStoredFile]     = useState<File | null>(null);
  const [mapping,        setMapping]        = useState<Record<string, string>>({});
  const [applyingMap,    setApplyingMap]    = useState(false);
  const [parsing,        setParsing]        = useState(false);
  const [downloading,    setDownloading]    = useState(false);
  const [error,          setError]          = useState<string | null>(null);
  const [batchId,        setBatchId]        = useState<string | null>(null);
  const [rows,           setRows]           = useState<TicketRow[]>([]);
  // The grid was changed by hand since the file was last read — re-reading it would drop that.
  const [rowsEdited,     setRowsEdited]     = useState(false);
  const downloadLinkRef  = useRef<HTMLAnchorElement>(null);

  // ── Statement form state ───────────────────────────────────────────────────
  const [statementType, setStatementType] = useState<StatementType>("B2B");
  const [agency,        setAgency]        = useState("");
  // Customer mode only: WHO the tickets were sold to.
  const [tag,           setTag]           = useState<CustomerTag>(EMPTY_TAG);
  // Opened from a Customer data → Statement tab (B2B / Corporate / Direct): start on that
  // customer type. Read once on mount from the URL — not useSearchParams, which would need
  // a Suspense boundary around every page that renders this wizard.
  useEffect(() => {
    if (!isCustomer || typeof window === "undefined") return;
    const t = new URLSearchParams(window.location.search).get("customer_type");
    if (t === "agency" || t === "corporate" || t === "direct") setTag({ ...EMPTY_TAG, customerType: t });
  }, [isCustomer]);
  const [statementName, setStatementName] = useState("");
  const [agencyOptions, setAgencyOptions] = useState<string[]>([]);
  // The statement must record WHICH onboarded agency it belongs to, not just a
  // vendor name. A vendor is onboarded once per branch, so "Lords Travels" alone
  // matches both Lords Delhi and Lords Mumbai — and Agency Billing then refuses
  // to bill it rather than guess which branch's tickets these are.
  const [agencyDirectory, setAgencyDirectory] = useState<AgencyOpt[]>([]);

  useEffect(() => {
    api.get<AgencyOpt[]>("/agencies/", { params: { limit: 1000 } })
      .then(r => {
        setAgencyDirectory(r.data);
        setAgencyOptions(r.data.map(agencyOptionLabel));
      })
      .catch(() => {});
  }, []);

  // The picker stores its label, so map back to the row it names.
  const selectedAgency = agencyDirectory.find(a => agencyOptionLabel(a) === agency) ?? null;
  const [validFrom,   setValidFrom]   = useState("");
  const [validTo,     setValidTo]     = useState("");
  const [formTouched, setFormTouched] = useState(false);

  // ── The declared date format (Internal Statement — `askDateFormats`) ──────
  // What the user chose, else what the file shows (`/upload/detect-date-formats`), else this
  // customer's last statement — `useDateFormats`. The rows are read in it at the extract that
  // applies the mapping, so changing it on the preview reads the file again.
  const dateFields = askDateFormats ? TICKET_DATE_FIELDS : NO_DATE_FIELDS;
  const [detected, setDetected] = useState<{ file: File; byField: Record<string, DetectedFormat> } | null>(null);
  const [detecting, setDetecting] = useState(false);
  const detectSeq = useRef(0);
  const partyKey = JSON.stringify(buildTagPayload(tag));
  const [lastFormats, setLastFormats] = useState<{ key: string; formats: Partial<DateFormats> } | null>(null);
  const dates = useDateFormats(
    dateFields,
    detected && detected.file === storedFile ? detected.byField : null,
    lastFormats && lastFormats.key === partyKey ? lastFormats.formats : null,
    detecting,
    { lastUpload: "This customer's last statement", who: "this customer's system" },
  );

  // Customer mode is gated on the customer tag; internal mode on the vendor agency.
  const isStatementComplete = (isCustomer
    ? (isTagComplete(tag) && validFrom !== "" && validTo !== "" && validTo >= validFrom)
    : statementComplete(agency, validFrom, validTo)) && dates.complete;

  // ── Internal Statement: duplicates (`duplicateCheck`) ──────────────────────
  const [dupCheck,      setDupCheck]      = useState<DuplicateCheck | null>(null);
  const [dupBusy,       setDupBusy]       = useState(false);
  const [dupError,      setDupError]      = useState<string | null>(null);
  const dupSeq = useRef(0);
  const [savedReport,   setSavedReport]   = useState<{ created: number; duplicates: DuplicateReport | null } | null>(null);

  // ── Internal Statement: details filled in from the file (`fillFromFile`) ────
  // `…Guessed`: the value came from the file, so the next file's reading may replace it —
  // what the user picked or typed is never replaced. `nameAuto`: the statement name
  // follows the customer and the period until the user types one of their own.
  const [tagGuessed,    setTagGuessed]    = useState(false);
  const [periodGuessed, setPeriodGuessed] = useState(false);
  const [nameAuto,      setNameAuto]      = useState(true);
  const [partyHint,     setPartyHint]     = useState<FieldHint | null>(null);
  const [periodHint,    setPeriodHint]    = useState<FieldHint | null>(null);

  // The panel's own edits — the user's answer, so nothing read off a file replaces it.
  const pickTag = (t: CustomerTag) => {
    setTag(t);
    setTagGuessed(false);
    setPartyHint(h => (h?.candidates?.some(c => c.customer_type === t.customerType) ? h : null));
  };
  const typeFrom = (v: string) => { setValidFrom(v); setPeriodGuessed(false); setPeriodHint(null); };
  const typeTo = (v: string) => { setValidTo(v); setPeriodGuessed(false); setPeriodHint(null); };
  const typeName = (v: string) => { setStatementName(v); setNameAuto(v.trim() === ""); };

  // "B2B - Globe Air Travels - 2026-08-01" — the name the server would give a blank one,
  // shown filled in so the user sees it before saving.
  useEffect(() => {
    if (!fillFromFile || !nameAuto) return;
    const t = tag.customerType;
    setStatementName(t && tag.partyName && validFrom ? `${CUSTOMER_TYPE_LABEL[t]} - ${tag.partyName} - ${validFrom}` : "");
  }, [fillFromFile, nameAuto, tag.customerType, tag.partyName, validFrom]);

  // ── Editable row handlers ─────────────────────────────────────────────────
  const handleTicketRowChange = useCallback((idx: number, key: string, val: string) => {
    setRowsEdited(true);
    setRows(prev => prev.map((r, i) => {
      if (i !== idx) return r;
      const col = TICKET_COL_GROUPS.flatMap(g => g.cols).find(c => c.key === key);
      return { ...r, [key]: col?.type === "number" ? (val === "" ? null : parseFloat(val)) : (val || null) };
    }));
  }, []);
  const handleDeleteTicketRow = useCallback((idx: number) => {
    setRowsEdited(true);
    setRows(prev => prev.filter((_, i) => i !== idx));
  }, []);
  const handleAddTicketRow = () => {
    setRowsEdited(true);
    setRows(prev => [...prev, { row_order: prev.length } as TicketRow]);
  };

  // ── Filter + bulk edit state & handlers ───────────────────────────────────
  const [filterText,   setFilterText]   = useState("");
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set());
  const [bulkColKey,   setBulkColKey]   = useState("");
  const [bulkColValue, setBulkColValue] = useState("");

  const handleToggleRow = useCallback((idx: number) => {
    setSelectedRows(prev => { const next = new Set(prev); next.has(idx) ? next.delete(idx) : next.add(idx); return next; });
  }, []);
  const handleToggleAllFiltered = useCallback((filteredIndices: number[], allSelected: boolean) => {
    setSelectedRows(prev => { const next = new Set(prev); if (allSelected) filteredIndices.forEach(i => next.delete(i)); else filteredIndices.forEach(i => next.add(i)); return next; });
  }, []);
  const handleBulkApply = () => {
    if (!bulkColKey || bulkColValue === "") return;
    const col = TICKET_COL_GROUPS.flatMap(g => g.cols).find(c => c.key === bulkColKey);
    setRowsEdited(true);
    setRows(prev => prev.map((r, i) => {
      if (!selectedRows.has(i)) return r;
      return { ...r, [bulkColKey]: col?.type === "number" ? (bulkColValue === "" ? null : parseFloat(bulkColValue)) : (bulkColValue || null) };
    }));
    setBulkColValue("");
  };
  const resetFilter = () => { setFilterText(""); setSelectedRows(new Set()); setBulkColKey(""); setBulkColValue(""); };

  // ── Template download ────────────────────────────────────────────────────
  const handleDownloadTemplate = async () => {
    setDownloading(true);
    try {
      const typeParam = statementType.toLowerCase();
      const resp = await api.get(`${apiBase}/template/download?type=${typeParam}`, { responseType: "blob" });
      const url  = URL.createObjectURL(resp.data as Blob);
      const a    = downloadLinkRef.current!;
      a.href     = url;
      a.download = statementType === "AIRLINE" ? "airline_ticket_template.xlsx" : "ticket_template.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Failed to download template.");
    } finally {
      setDownloading(false);
    }
  };

  // ── Step 1: drag-drop → extract ──────────────────────────────────────────
  // `sheet` and `headerRow` are what the server DETECTED on this file. They are
  // echoed back on every later read of it so the second parse sees exactly the
  // columns the mapping was built against — a mapping is a list of column names,
  // so a header detected one row out would rename all of them and discard it.
  const [sheet,     setSheet]     = useState<string | null>(null);
  const [headerRow, setHeaderRow] = useState<number | null>(null);

  const runExtract = useCallback(async (
    file: File,
    opts: {
      mapping?: Record<string, string>; sheet?: string | null; headerRow?: number | null;
      // Internal Statement: how the dates are written, and the period that settles the
      // Excel-stored ones — the read that makes the rows.
      dateFormats?: DateFormats; period?: { from: string; to: string };
    } = {},
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("statement_type", statementType);
    if (opts.mapping) form.append("column_mapping", JSON.stringify(opts.mapping));
    if (opts.sheet) form.append("sheet_name", opts.sheet);
    if (opts.headerRow !== null && opts.headerRow !== undefined) {
      form.append("header_row", String(opts.headerRow));
    }
    if (opts.dateFormats) form.append("date_formats", JSON.stringify(opts.dateFormats));
    if (opts.period) {
      form.append("valid_from", opts.period.from);
      form.append("valid_to", opts.period.to);
    }
    const { data } = await api.post<ExtractionPreview>(`${apiBase}/upload/extract`, form);
    return data;
  }, [statementType, apiBase]);

  // What the file shows about how it writes its dates — asked once it has been read, and again
  // when the period changes: the period settles a date that reads both ways round.
  const hasPreview = preview != null;
  const detectPeriod = validFrom && validTo && validTo >= validFrom ? `${validFrom}|${validTo}` : "";
  useEffect(() => {
    if (!askDateFormats || !storedFile || !hasPreview) return;
    const seq = ++detectSeq.current;
    const timer = setTimeout(async () => {
      setDetecting(true);
      try {
        const fd = new FormData();
        fd.append("file", storedFile);
        if (sheet) fd.append("sheet_name", sheet);
        if (headerRow != null) fd.append("header_row", String(headerRow));
        if (detectPeriod) {
          const [from, to] = detectPeriod.split("|");
          fd.append("valid_from", from);
          fd.append("valid_to", to);
        }
        const { data } = await api.post<{ fields: DetectedFormat[] }>(`${apiBase}/upload/detect-date-formats`, fd);
        if (seq !== detectSeq.current) return;
        setDetected({ file: storedFile, byField: Object.fromEntries(data.fields.map(d => [d.field, d])) });
      } catch {
        if (seq === detectSeq.current) setDetected({ file: storedFile, byField: {} });   // the user chooses
      } finally {
        if (seq === detectSeq.current) setDetecting(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [askDateFormats, storedFile, hasPreview, sheet, headerRow, detectPeriod, apiBase]);

  // How this customer's last statement was read — a customer system writes dates the same way.
  useEffect(() => {
    if (!askDateFormats) return;
    const params = Object.fromEntries(
      Object.entries(JSON.parse(partyKey) as Record<string, unknown>).filter(([, v]) => v != null && v !== ""));
    if (!params.customer_agency_id && !params.corporate_id && !params.customer_id) return;
    let live = true;
    api.get<{ date_formats: Partial<DateFormats> | null }>(`${apiBase}/upload/last-date-formats`, { params })
      .then(({ data }) => { if (live) setLastFormats({ key: partyKey, formats: data.date_formats ?? {} }); })
      .catch(() => { /* the file, or the user, decides */ });
    return () => { live = false; };
  }, [askDateFormats, partyKey, apiBase]);

  /** Internal Statement: fill in what the file says about itself — the days it covers (its
   *  name, else its header line) and who it is for (a name in it matched against the user's
   *  agencies and corporates). Dates typed and a customer picked by the user are theirs. */
  const applyGuess = async (fileName: string, data: ExtractionPreview) => {
    let g: GuessResp | null = null;
    try {
      g = (await api.post<GuessResp>(`${apiBase}/upload/guess`, { file_name: fileName, preamble: data.preamble ?? [] })).data;
    } catch { /* nothing filled in — the user enters the details */ }

    const period = g?.period ?? null;
    const typedDates = !periodGuessed && !!(validFrom || validTo);
    if (!typedDates) {
      setValidFrom(period?.from ?? "");
      setValidTo(period?.to ?? "");
      setPeriodGuessed(!!period);
      setPeriodHint(period
        ? { tone: "ok", text: `${period.label} — read from the ${period.source}. Check it.`
            + (g?.header_period ? ` The statement header says ${g.header_period.label}.` : "") }
        : { tone: "ask", text: "The file doesn't say which days it covers — enter the period." });
    } else if (period && (period.from !== validFrom || period.to !== validTo)) {
      setPeriodHint({ tone: "ask", text: `The ${period.source} says ${period.label}.` });
    }

    const p = g?.party;
    const pickedByUser = !tagGuessed && (tag.agencyId != null || tag.corporateId != null || tag.customerId != null);
    if (!p || pickedByUser) {
      if (p?.status === "resolved" && p.name && p.id != null && p.customer_type
          && !(p.customer_type === tag.customerType && (p.id === tag.agencyId || p.id === tag.corporateId))) {
        setPartyHint({ tone: "ask", text: `The ${p.source} names ${p.name}.`,
          candidates: [{ customer_type: p.customer_type, id: p.id, name: p.name }] });
      }
      return;
    }
    const typeChosen = !tagGuessed && tag.customerType != null;
    const why = p.narrowed_by === "previous upload" ? " — the branch you filed it under last time"
      : p.narrowed_by === "branch" ? " — the branch the file names" : "";
    if (p.status === "resolved" && p.id != null && p.customer_type && (!typeChosen || tag.customerType === p.customer_type)) {
      setTag({
        customerType: p.customer_type,
        agencyId: p.customer_type === "agency" ? p.id : null,
        corporateId: p.customer_type === "corporate" ? p.id : null,
        customerId: null,
        partyName: p.name ?? "",
      });
      setTagGuessed(true);
      setPartyHint({
        tone: "ok",
        text: `Identified from the ${p.source}${p.matched ? ` (“${p.matched}”)` : ""}${why}. Change it if it is wrong.`,
        candidates: p.candidates.length > 1 ? p.candidates : undefined,
      });
    } else if (p.status !== "unresolved") {
      if (p.customer_type && !typeChosen) {
        setTag({ ...EMPTY_TAG, customerType: p.customer_type });
        setTagGuessed(true);
      }
      const candidates = p.candidates.length ? p.candidates
        : p.id != null && p.customer_type ? [{ customer_type: p.customer_type, id: p.id, name: p.name ?? "" }] : [];
      setPartyHint({
        tone: "ask",
        text: p.status === "ambiguous"
          ? `The ${p.source} could be ${candidates.length} of your customers${p.matched ? ` (“${p.matched}”)` : ""} — pick the right one:`
          : `The ${p.source} names ${p.name}:`,
        candidates,
      });
    } else {
      if (tagGuessed) { setTag(EMPTY_TAG); setTagGuessed(false); }
      setPartyHint(null);
    }
  };

  // A plain function, not useCallback: it reads the details as they stand on each drop.
  const onDrop = async (files: File[]) => {
    if (!files[0]) return;
    setError(null);
    setParsing(true);
    setStoredFile(files[0]);
    try {
      const data = await runExtract(files[0]);
      setPreview(data);
      setMapping(data.suggested_mapping ?? {});
      setSheet(data.sheet_name ?? null);
      setHeaderRow(data.header_row ?? 0);
      if (fillFromFile) {
        // Stay on this step: the details the file gave are filled in for the user to check,
        // with the date format, and Next goes on to the mapping.
        await applyGuess(files[0].name, data);
      } else {
        // The statement's own period line, e.g. "For The Period 8 August 2026 To
        // 15 August 2026". Only ever fills a blank — a date the user already typed
        // is their answer, not ours.
        if (data.detected_from && !validFrom) setValidFrom(data.detected_from);
        if (data.detected_to && !validTo) setValidTo(data.detected_to);
        setStep("mapping");
      }
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to parse file. Please check the format.");
      setStoredFile(null);
    } finally {
      setParsing(false);
    }
  };

  /** Back to the drop zone with the details kept — what this file filled in may be
   *  replaced by the next one; what the user entered stays. */
  const changeFile = () => {
    setPreview(null); setStoredFile(null); setMapping({}); setSheet(null); setHeaderRow(null);
    setDupCheck(null); setRows([]);
  };

  /** "Next: map columns" (`fillFromFile`): once the details — the date format included — are
   *  complete. The panel and the date format box say what is missing. */
  const startNext = () => {
    setFormTouched(true);
    if (!isStatementComplete) return;
    setError(null);
    setStep("mapping");
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    // Matched by EXTENSION as well as MIME. The extension arrays used to be empty,
    // so acceptance depended entirely on what the OS reported — and Windows reports
    // plenty of .xls files as application/octet-stream. With no onDropRejected
    // either, such a file was silently ignored: the user dropped it and nothing
    // happened at all.
    accept: {
      "application/vnd.ms-excel": [".xls"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx", ".xlsm"],
      "text/csv": [".csv"],
      "text/plain": [".tsv", ".txt"],
      "application/octet-stream": [".xls", ".xlsx", ".xlsm", ".csv"],
    },
    onDropRejected: (rejections) => {
      const name = rejections[0]?.file?.name ?? "That file";
      setError(
        rejections.length > 1
          ? "Upload one file at a time."
          : `${name} is not a spreadsheet this importer reads. Upload an .xls, .xlsx or .csv file.`,
      );
    },
    maxFiles: 1,
    disabled: parsing,
  });

  // ── Step 2: apply user mapping → re-extract ──────────────────────────────
  // `formats` — a date format just changed on the preview, before the state holding it has.
  const applyMapping = async (formats?: DateFormats) => {
    if (!storedFile || !preview) return;
    setApplyingMap(true);
    setError(null);
    try {
      const data = await runExtract(storedFile, {
        mapping, sheet, headerRow,
        ...(askDateFormats ? {
          dateFormats: formats ?? dates.formats,
          period: validFrom && validTo ? { from: validFrom, to: validTo } : undefined,
        } : {}),
      });
      setPreview(data);
      setRows(data.rows);
      setRowsEdited(false);
      resetFilter();
      setOnlyDuplicates(false);
      setStep("preview");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to apply mapping.");
    } finally {
      setApplyingMap(false);
    }
  };

  /** Re-read the file at a different sheet or header row, and re-propose a mapping.
   *
   *  This is the control that makes an arbitrary statement workable: when detection
   *  picks the wrong row — a second title line, a sheet of notes in front of the
   *  data — the person holding the file can point at the right one. The mapping is
   *  discarded deliberately, because it names columns that no longer exist. */
  const reread = async (next: { sheet?: string; headerRow?: number }) => {
    if (!storedFile) return;
    setApplyingMap(true);
    setError(null);
    const nextSheet = next.sheet ?? sheet;
    const nextHeader = next.headerRow ?? (next.sheet ? null : headerRow);
    try {
      const data = await runExtract(storedFile, { sheet: nextSheet, headerRow: nextHeader });
      setPreview(data);
      setMapping(data.suggested_mapping ?? {});
      setSheet(data.sheet_name ?? null);
      setHeaderRow(data.header_row ?? 0);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to re-read the file.");
    } finally {
      setApplyingMap(false);
    }
  };

  // Asked again after every edit, add and delete — a corrected ticket number, passenger, date
  // or amount can turn a duplicate into a new ticket, and row positions move. Who the tickets
  // were sold to and the period do not enter into it, so it is asked as soon as there are rows.
  useEffect(() => {
    if (!duplicateCheck || step !== "preview" || rows.length === 0) return;
    const seq = ++dupSeq.current;
    setDupBusy(true);
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.post<DuplicateCheck>(`${apiBase}/upload/duplicates`, {
          // The source cells are not compared, so they are not sent (undefined drops out of JSON).
          rows: rows.map(r => ({ ...r, raw_data: undefined })),
        });
        if (seq !== dupSeq.current) return;
        setDupCheck(data);
        setDupError(null);
      } catch (e: unknown) {
        if (seq !== dupSeq.current) return;
        setDupCheck(null);
        setDupError(apiDetail(e) ?? "Could not check these tickets for duplicates. Saving will still check them.");
      } finally {
        if (seq === dupSeq.current) setDupBusy(false);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [duplicateCheck, step, rows, apiBase]);

  // Duplicate rows → where the ticket already is, for the grid. `onlyDuplicates` narrows the
  // grid to them, falling back to every row once none is left — so fixing the last one does
  // not empty it.
  const duplicateRows = useMemo(() => {
    const out = new Map<number, string>();
    for (const d of dupCheck?.rows ?? []) out.set(d.index, duplicateOf(d, dupCheck?.statements ?? []));
    return out;
  }, [dupCheck]);
  const nothingNew = duplicateCheck && dupCheck != null && !dupCheck.can_save;
  const [onlyDuplicates, setOnlyDuplicates] = useState(false);
  const onlyRows = useMemo(
    () => (onlyDuplicates && duplicateRows.size > 0 ? new Set(duplicateRows.keys()) : null),
    [onlyDuplicates, duplicateRows]);

  const activeFields    = mappingFieldsFor(statementType);
  const requiredKeys    = activeFields.filter(f => f.mapRequired).map(f => f.key);
  const missingRequired = requiredKeys.filter(k => !mapping[k] || mapping[k] === SKIP);

  // ── How the dates read (Internal Statement) ──────────────────────────────
  // Counted off the rows as they stand — edits included — so a date set in the grid leaves
  // the "not read" count at once. A loop, not forEach: the span is assigned as it goes.
  const datesRead: DatesRead[] = useMemo(() => dateFields.map((f) => {
    // A file with only a Doc Date (GLOBE's ticket statement) shows that under the Ticket
    // Date's format, which it follows — rather than "no dates read" for a column it never had.
    const value = (r: TicketRow, k: string) => (r as Record<string, unknown>)[k];
    const viaDoc = f.field === "ticket_date" && !rows.some(r => value(r, "ticket_date")) && rows.some(r => value(r, "doc_date"));
    const key = viaDoc ? "doc_date" : f.field;
    let read = 0;
    let first: string | null = null;
    let last: string | null = null;
    const cells: { index: number; value: string | null }[] = [];
    for (let i = 0; i < rows.length; i++) {
      const v = value(rows[i], key);
      if (v == null || v === "") continue;
      const s = String(v);
      if (!ISO_DAY.test(s)) { cells.push({ index: i, value: s }); continue; }
      const d = s.slice(0, 10);
      read++;
      if (first == null || d < first) first = d;
      if (last == null || d > last) last = d;
    }
    const isMapped = (k: string) => !!mapping[k] && mapping[k] !== SKIP;
    return { ...f, header: viaDoc ? "Doc Date" : f.header,
      format: dates.formats[f.field] ?? null, read, first, last, unreadable: cells.length, cells,
      // A file with only a Doc Date has it as its ticket date.
      mapped: isMapped(f.field) || (f.field === "ticket_date" && isMapped("doc_date")) };
  }), [dateFields, rows, mapping, dates.formats]);

  // Changing a format on the preview reads the file again in it; hand edits are asked about first.
  const [pendingFormat, setPendingFormat] = useState<{ field: string; order: DateOrder } | null>(null);
  const rereadInFormat = (field: string, order: DateOrder) => {
    dates.choose(field, order);
    void applyMapping({ ...dates.formats, [field]: order });
  };
  const changeFormatOnPreview = (field: string, order: DateOrder) => {
    if (dates.formats[field] === order) return;
    if (rowsEdited) setPendingFormat({ field, order });
    else rereadInFormat(field, order);
  };
  const datesText = askDateFormats && dates.complete
    ? `Dates ${dateFields.map(f => orderLabel(dates.formats[f.field])).join(" / ")}` : "";

  // ── Step 3: confirm → save ────────────────────────────────────────────────
  const confirmUpload = async () => {
    setFormTouched(true);
    if (!isStatementComplete || !preview) return;
    setStep("saving");
    setError(null);
    try {
      const { data } = await api.post<{ batch_id: string; created_count: number; duplicates?: DuplicateReport | null }>(
        `${apiBase}/upload/confirm`,
        {
          file_name:      preview.file_name,
          rows,
          // A customer statement is always B2B-shaped: the airline field set
          // belongs to a vendor file, and those go through Vendors → Statements.
          statement_type: isCustomer ? "B2B" : statementType,
          // Name for display, id for billing. Without the id, two branches of one
          // vendor both match this statement and neither can safely bill it.
          // In customer mode the server re-derives both from the authorised party.
          agency: isCustomer ? (tag.partyName || "—") : (selectedAgency?.name ?? agency),
          agency_id: isCustomer ? null : (selectedAgency?.id ?? null),
          ...(isCustomer ? buildTagPayload(tag) : {}),
          statement_name: statementName.trim() || null,
          valid_from:     validFrom,
          valid_to:       validTo,
          // How the rows' dates were read — kept on the statement (Internal Statement).
          ...(askDateFormats ? { date_formats: dates.formats } : {}),
        },
      );
      setBatchId(data.batch_id);
      setSavedReport({ created: data.created_count, duplicates: data.duplicates ?? null });
      if (storedFile && data.batch_id) {
        console.log("[GCS] Uploading ticket file to bucket | batch_id=", data.batch_id, "| file=", storedFile.name, "| size=", storedFile.size);
        try {
          const fd = new FormData();
          fd.append("file", storedFile);
          const res = await api.post(`${apiBase}/statements/${data.batch_id}/file`, fd, {
            headers: { "Content-Type": "multipart/form-data" },
          });
          console.log("[GCS] Ticket file upload SUCCESS | response=", res.data);
        } catch (uploadErr) {
          console.error("[GCS] Ticket file upload FAILED:", uploadErr);
        }
      } else {
        console.warn("[GCS] Skipping file upload | storedFile=", storedFile, "| batch_id=", data.batch_id);
      }
      setStep("done");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to save tickets.");
      setStep("preview");
    }
  };

  const reset = () => {
    setStep("drop"); setPreview(null); setStoredFile(null);
    setMapping({}); setBatchId(null); setError(null); setRows([]); resetFilter();
    setStatementType("B2B"); setAgency(""); setStatementName("");
    setValidFrom(""); setValidTo(""); setFormTouched(false);
    // The customer too — "Upload Another" is a new statement, and a kept customer would
    // stop the next file's own customer being read off it.
    setTag(EMPTY_TAG); setSheet(null); setHeaderRow(null);
    setTagGuessed(false); setPeriodGuessed(false); setNameAuto(true);
    setPartyHint(null); setPeriodHint(null);
    setDupCheck(null); setDupError(null); setSavedReport(null); setOnlyDuplicates(false);
    dates.reset(); setDetected(null); setRowsEdited(false);
  };

  // What the summary bars and the done screen say the statement is: the CUSTOMER in
  // customer mode (it used to read the vendor-mode `agency`, which this mode never sets).
  const badgeText = isCustomer ? (tag.customerType ? CUSTOMER_TYPE_LABEL[tag.customerType] : "—") : statementType;
  const partyText = isCustomer ? (tag.partyName || (tag.customerType === "direct" ? "Walk-in customer" : "")) : agency;
  const periodText = validFrom && validTo ? (isCustomer ? formatPeriod(validFrom, validTo) : `${validFrom} – ${validTo}`) : "";

  const isDone = step === "done";

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      <a ref={downloadLinkRef} className="hidden" />

      {/* page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/customers/statements" className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
            <ChevronLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Upload Tickets</h1>
            <p className="text-xs text-gray-500 mt-0.5">Create a new statement and import supplier XLS/XLSX</p>
          </div>
        </div>

        {/* Step indicator */}
        {!isDone && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            {(["drop", "mapping", "preview", "done"] as Step[]).map((s, i) => {
              const labels: Record<Step, string> = { drop: "Upload", mapping: "Map Columns", preview: "Preview", saving: "Saving", done: "Done" };
              const active  = step === s;
              const passed  = ["drop", "mapping", "preview", "saving", "done"].indexOf(step) > i;
              return (
                <div key={s} className="flex items-center gap-1.5">
                  {i > 0 && <span className="text-gray-300">›</span>}
                  <span className={`px-2.5 py-0.5 rounded-full font-medium ${
                    active  ? "bg-[#1e3a5f] text-white" :
                    passed  ? "bg-green-100 text-green-700" :
                              "bg-gray-100 text-gray-400"
                  }`}>
                    {labels[s as Step] ?? s}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* error banner */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
          <button onClick={() => setError(null)} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {/* ── Done screen (full width, no split) ─────────────────────────────── */}
      {isDone && batchId && preview && (
        <div className="max-w-md mx-auto text-center space-y-5 py-10">
          <div className="w-16 h-16 bg-green-50 rounded-full flex items-center justify-center mx-auto">
            <CheckCircle className="w-8 h-8 text-green-600" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900">Statement Created</h2>
            <p className="text-sm font-medium text-gray-700 mt-1">
              <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold mr-2 ${statementType === "AIRLINE" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700"}`}>{badgeText}</span>
              {partyText}
            </p>
            <p className="text-xs text-gray-500 mt-0.5">
              {periodText}
            </p>
            <p className="text-sm text-gray-500 mt-2">
              {(savedReport?.created ?? rows.length).toLocaleString("en-IN")} tickets saved from <span className="font-medium">{preview.file_name}</span>
            </p>
            {!!savedReport?.duplicates?.duplicates && (
              <p className="text-xs text-amber-700 mt-1.5">
                {savedReport.duplicates.duplicates.toLocaleString("en-IN")} of the file&apos;s{" "}
                {savedReport.duplicates.total.toLocaleString("en-IN")} tickets were duplicates
                {savedReport.duplicates.statements.length > 0 && (
                  <> of tickets already loaded (in {savedReport.duplicates.statements
                    .map(s => s.statement_name ?? s.file_name ?? "an earlier statement").join(", ")})</>
                )} and were ignored.
              </p>
            )}
            <p className="text-xs text-gray-400 mt-0.5 font-mono">Batch: {batchId}</p>
          </div>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={reset}
              className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50"
            >
              Upload Another
            </button>
            <button
              onClick={() => router.push(listHref ?? sectionBase)}
              className="flex items-center gap-2 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#16304f]"
            >
              <FileSpreadsheet className="w-4 h-4" /> View Ticket Repository
            </button>
          </div>
        </div>
      )}

      {/* ── Saving screen ──────────────────────────────────────────────────── */}
      {step === "saving" && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center space-y-3">
            <RefreshCw className="w-8 h-8 text-blue-500 animate-spin mx-auto" />
            <p className="text-sm text-gray-600">Saving statement and tickets to database…</p>
          </div>
        </div>
      )}

      {/* ── Drop step — two-panel layout ──────────────────────────────────── */}
      {step === "drop" && (
        <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-6 items-start">
          {/* LEFT: Statement form */}
          {isCustomer ? (
            <CustomerPartyPanel
              tag={tag} setTag={fillFromFile ? pickTag : setTag}
              statementName={statementName} setStatementName={fillFromFile ? typeName : setStatementName}
              validFrom={validFrom}         setValidFrom={fillFromFile ? typeFrom : setValidFrom}
              validTo={validTo}             setValidTo={fillFromFile ? typeTo : setValidTo}
              touched={formTouched}
              partyHint={fillFromFile ? partyHint : null}
              periodHint={fillFromFile ? periodHint : null}
              nameHint={fillFromFile && nameAuto && statementName
                ? "Filled in from the customer and the period — type your own to change it." : null}
            />
          ) : (
            <StatementFormPanel
              statementType={statementType} setStatementType={setStatementType}
              agency={agency}               setAgency={setAgency}
              statementName={statementName}   setStatementName={setStatementName}
              agencyOptions={agencyOptions}
              validFrom={validFrom}         setValidFrom={setValidFrom}
              validTo={validTo}             setValidTo={setValidTo}
              touched={formTouched}
              isComplete={isStatementComplete}
            />
          )}
          {/* RIGHT: dropzone */}
          <div className="space-y-4 min-w-0">

            {/* drop content */}
            <div className="space-y-4">
              <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 flex items-start gap-4">
                <FileSpreadsheet className="w-8 h-8 text-blue-500 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-blue-800 mb-0.5">Download the ticket template</p>
                  <p className="text-xs text-blue-600 leading-relaxed">
                    Use our template for instant column auto-mapping. If you have your own format,
                    upload it and we&apos;ll guide you through column mapping.
                  </p>
                </div>
                <button
                  onClick={handleDownloadTemplate}
                  disabled={downloading}
                  className="flex items-center gap-1.5 shrink-0 px-3.5 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-lg text-xs font-semibold transition-colors"
                >
                  {downloading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                  {downloading ? "Downloading…" : "Download Template"}
                </button>
              </div>

              {fillFromFile && preview && storedFile ? (
                <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
                  <div className="flex items-center gap-3 rounded-lg border border-green-200 bg-green-50/50 p-3">
                    <FileSpreadsheet className="w-8 h-8 text-green-600 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-gray-800 truncate" title={preview.file_name}>{preview.file_name}</p>
                      <p className="text-xs text-gray-500">
                        {preview.total_rows.toLocaleString("en-IN")} rows read{preview.sheet_name ? ` · sheet ${preview.sheet_name}` : ""}
                      </p>
                    </div>
                    <button onClick={changeFile} className="text-xs text-gray-500 underline hover:text-red-600 shrink-0">Change file</button>
                  </div>
                  {/* How this file writes its dates — read off it, beside it, where there is
                      room for each column on one line. Needed before Next. */}
                  {askDateFormats && (
                    <div className={`rounded-lg border p-4 ${
                      formTouched && !dates.complete ? "border-red-200 bg-red-50/30" : "border-gray-200"}`}>
                      <DateFormatSection fields={dateFields} formats={dates.formats} onChoose={dates.choose}
                        note={dates.note} detecting={detecting} />
                      {formTouched && !dates.complete && (
                        <p className="text-[11px] text-red-500 mt-2">
                          Choose the date format of {dates.missing.map(f => f.header).join(" and ")}.
                        </p>
                      )}
                    </div>
                  )}
                  <p className="text-xs text-gray-500">
                    Check the statement details on the left — the customer, the period and the name are filled in
                    from the file wherever it says them{askDateFormats ? ", and the date format from how its dates are written" : ""}.
                    Change anything that is wrong, then press Next to map the columns.
                  </p>
                  <div className="flex justify-end">
                    <button onClick={startNext}
                      className="flex items-center gap-1.5 px-5 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f] disabled:opacity-50">
                      Next: map columns <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ) : (
              <div className="bg-white rounded-xl border border-gray-200 p-6">
                <div
                  {...getRootProps()}
                  className={`border-2 border-dashed rounded-xl p-14 text-center cursor-pointer transition-colors ${
                    isDragActive ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-gray-400"
                  } ${parsing ? "opacity-60 cursor-not-allowed" : ""}`}
                >
                  <input {...getInputProps()} />
                  {parsing
                    ? <RefreshCw className="w-10 h-10 mx-auto text-blue-400 mb-3 animate-spin" />
                    : <Upload className="w-10 h-10 mx-auto text-gray-400 mb-3" />}
                  <p className="text-sm font-medium text-gray-700">
                    {parsing ? "Parsing file…" : isDragActive ? "Drop the file here" : "Drag & drop XLS / XLSX"}
                  </p>
                  {!parsing && <p className="text-xs text-gray-400 mt-1">or click to browse</p>}
                </div>
              </div>
              )}
            </div>
          </div>{/* /right panel */}
        </div>
      )}{/* /drop two-panel */}

      {/* ── Mapping step — full width ──────────────────────────────────────── */}
      {step === "mapping" && preview && (
        <div className="space-y-4">
          {/* statement summary bar */}
          <div className="bg-[#1e3a5f]/5 border border-[#1e3a5f]/20 rounded-xl px-5 py-3 flex items-center gap-4 flex-wrap">
            <FileText className="w-4 h-4 text-[#1e3a5f] shrink-0" />
            <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wide ${statementType === "AIRLINE" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700"}`}>{badgeText}</span>
            <span className="text-xs font-semibold text-[#1e3a5f]">{partyText || <span className="text-red-400 italic">{isCustomer ? "Customer missing" : "Agency missing"}</span>}</span>
            <span className="text-gray-300 text-xs">·</span>
            <span className="text-xs text-gray-600">{periodText || <span className="text-red-400 italic">Dates missing</span>}</span>
            {datesText && <><span className="text-gray-300 text-xs">·</span><span className="text-xs text-gray-600">{datesText}</span></>}
            {!isStatementComplete && (
              <button
                onClick={() => setStep("drop")}
                className="ml-auto text-xs text-amber-600 underline hover:text-amber-700"
              >
                ← Fill statement details
              </button>
            )}
          </div>

          <div className="flex items-center justify-between bg-white border border-gray-200 rounded-xl px-5 py-3">
            <div className="flex items-center gap-3">
              <FileSpreadsheet className="w-5 h-5 text-blue-600" />
              <div>
                <p className="text-sm font-semibold text-gray-800">{preview.file_name}</p>
                <p className="text-xs text-gray-500">{preview.total_rows} rows · {preview.xls_columns.length} columns detected</p>
              </div>
            </div>
            <button onClick={reset} className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-600 hover:bg-gray-50">
              Cancel
            </button>
          </div>

          {preview.is_template_match ? (
            <div className="bg-green-50 border border-green-200 rounded-xl px-5 py-4 flex items-start gap-3">
              <CheckCircle className="w-5 h-5 text-green-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-green-800">
                  All columns matched automatically ({Object.keys(preview.suggested_mapping).length} of {activeFields.length} fields)
                </p>
                <p className="text-xs text-green-600 mt-0.5">
                  This looks like our template. You can review the mapping below or proceed directly.
                </p>
              </div>
            </div>
          ) : (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-amber-800">
                  {Object.keys(preview.suggested_mapping).length} of {activeFields.length} columns auto-matched
                </p>
                <p className="text-xs text-amber-600 mt-0.5">
                  Map the remaining columns below, then click &quot;Apply Mapping&quot;.
                  Required fields are marked with <span className="text-red-500 font-bold">*</span>.
                </p>
              </div>
            </div>
          )}

          {preview.warnings.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-xs text-yellow-800 space-y-1">
              {preview.warnings.map((w, i) => (
                <div key={i} className="flex items-center gap-2"><AlertCircle className="w-3.5 h-3.5 shrink-0" />{w}</div>
              ))}
            </div>
          )}

          {/* Where in the file we are reading from. Shown always, not only on
              failure: if the header was detected one row out, this is the only
              place the user can see that and say so. */}
          <div className="bg-white border border-gray-200 rounded-xl px-5 py-3.5 space-y-3">
            <div className="flex flex-wrap items-end gap-4">
              {preview.sheet_names.length > 1 && (
                <label className="block">
                  <span className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Sheet</span>
                  <select
                    value={sheet ?? ""}
                    disabled={applyingMap}
                    onChange={e => reread({ sheet: e.target.value })}
                    className="border border-gray-200 rounded-lg px-3 py-1.5 text-xs bg-gray-50 disabled:opacity-50"
                  >
                    {preview.sheet_names.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
              )}
              <label className="block">
                <span className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Header row</span>
                <select
                  value={preview.header_row}
                  disabled={applyingMap}
                  onChange={e => reread({ headerRow: Number(e.target.value) })}
                  className="border border-gray-200 rounded-lg px-3 py-1.5 text-xs bg-gray-50 disabled:opacity-50"
                >
                  {Array.from({ length: 12 }, (_, i) => i).map(i => (
                    <option key={i} value={i}>
                      Row {i + 1}{i === preview.header_row ? " — detected" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <p className="text-[11px] text-gray-400 pb-1.5">
                Changing either re-reads the file and proposes a new mapping.
              </p>
            </div>

            {preview.preamble.length > 0 && (
              <p className="text-[11px] text-gray-500">
                <span className="font-semibold text-gray-600">Above the header:</span>{" "}
                {preview.preamble.slice(0, 4).join(" · ")}
                {preview.detected_from && preview.detected_to && (
                  <span className="ml-2 text-green-700">
                    → period read as {preview.detected_from} to {preview.detected_to}
                  </span>
                )}
              </p>
            )}

            {preview.unmapped_columns.length > 0 && (
              <p className="text-[11px] text-amber-700">
                <span className="font-semibold">
                  {preview.unmapped_columns.length} column{preview.unmapped_columns.length === 1 ? "" : "s"} in
                  your file {preview.unmapped_columns.length === 1 ? "is" : "are"} not mapped:
                </span>{" "}
                {preview.unmapped_columns.join(", ")}. Their values are still saved with the
                ticket, but nothing reports on them until they are mapped below.
              </p>
            )}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/50 flex items-center justify-between">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Column Mapping</p>
              <p className="text-xs text-gray-400">Select which column from your file maps to each field</p>
            </div>
            <div className="divide-y divide-gray-100 max-h-[460px] overflow-y-auto">
              {activeFields.map(field => {
                const mapped    = mapping[field.key];
                const isSkipped = !mapped || mapped === SKIP;
                return (
                  <div key={field.key} className="flex items-center px-5 py-2.5 gap-4">
                    <div className="w-48 shrink-0">
                      <span className="text-xs font-medium text-gray-700">{field.mapLabel ?? field.label}</span>
                      {field.mapRequired && <span className="text-red-500 ml-0.5 text-xs">*</span>}
                    </div>
                    <ArrowRight className="w-3.5 h-3.5 text-gray-300 shrink-0" />
                    <div className="flex-1 relative">
                      <select
                        value={mapped ?? SKIP}
                        onChange={e => setMapping(prev => ({ ...prev, [field.key]: e.target.value }))}
                        className={`w-full appearance-none text-xs border rounded-lg px-3 py-1.5 pr-7 focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                          isSkipped
                            ? field.mapRequired
                              ? "border-red-300 bg-red-50 text-red-600"
                              : "border-gray-200 bg-gray-50 text-gray-400"
                            : "border-green-300 bg-green-50 text-green-800"
                        }`}
                      >
                        <option value={SKIP}>— Skip / Not in file —</option>
                        {preview.xls_columns.map(col => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                      <ChevronDown className="w-3 h-3 text-gray-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    </div>
                    <div className="w-36 shrink-0">
                      {!isSkipped ? (
                        (() => {
                          // Up to three values, not one. When the first row of a
                          // column happens to be blank a single sample says
                          // "empty", which is exactly when the user most needs to
                          // see what is in there.
                          const samples = preview.sample_rows?.[mapped!]
                            ?? (preview.sample_row?.[mapped!] ? [preview.sample_row[mapped!]] : []);
                          if (!samples.length) return <span className="text-[10px] text-gray-300 italic">empty</span>;
                          return (
                            <div title={samples.join("\n")} className="space-y-0.5">
                              {samples.map((s, i) => (
                                <span key={i} className="block px-2 py-0.5 rounded bg-blue-50 border border-blue-100 text-[10px] font-mono text-blue-700 truncate">
                                  {s.length > 20 ? s.slice(0, 18) + "…" : s}
                                </span>
                              ))}
                            </div>
                          );
                        })()
                      ) : (
                        (() => {
                          // Nothing claimed this field, but a column looks close.
                          // Offered, never applied: a 0.82 name match on a money
                          // column is a good guess, not a fact.
                          const hint = preview.fuzzy_suggestions?.[field.key]?.[0];
                          if (!hint) return <span className="text-[10px] text-gray-200">—</span>;
                          return (
                            <button
                              type="button"
                              onClick={() => setMapping(prev => ({ ...prev, [field.key]: hint.column }))}
                              className="px-2 py-0.5 rounded bg-amber-50 border border-amber-200 text-[10px] text-amber-800 hover:bg-amber-100 truncate max-w-full"
                              title={`Use "${hint.column}" for this field`}
                            >
                              Use “{hint.column}”?
                            </button>
                          );
                        })()
                      )}
                    </div>
                    <div className="w-20 shrink-0 text-right">
                      {!isSkipped
                        ? <span className="inline-flex items-center gap-1 text-[10px] font-medium text-green-700 bg-green-100 px-2 py-0.5 rounded-full"><CheckCircle className="w-2.5 h-2.5" /> Mapped</span>
                        : field.mapRequired
                          ? <span className="text-[10px] font-medium text-red-500">Required</span>
                          : <span className="text-[10px] text-gray-300">Optional</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <div className="text-xs text-gray-500">
              {missingRequired.length > 0 && (
                <span className="text-red-500">
                  Required fields not mapped: {missingRequired.map(k => activeFields.find(f => f.key === k)?.mapLabel ?? k).join(", ")}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {/* One button, both branches. There used to be a second one for a
                  template match that jumped straight to the preview using the rows
                  the AUTO mapping produced — so every dropdown the user had just
                  corrected on a template-matched file was silently discarded. */}
              <button
                onClick={() => void applyMapping()}
                disabled={applyingMap || missingRequired.length > 0}
                className="flex items-center gap-1.5 px-5 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {applyingMap
                  ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Applying…</>
                  : <>Apply Mapping <ArrowRight className="w-3.5 h-3.5" /></>}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Preview step — full width ──────────────────────────────────────── */}
      {step === "preview" && preview && (
        <div className="space-y-3">
          {/* statement summary bar */}
          <div className="bg-[#1e3a5f]/5 border border-[#1e3a5f]/20 rounded-xl px-5 py-3 flex items-center gap-4 flex-wrap">
            <FileText className="w-4 h-4 text-[#1e3a5f] shrink-0" />
            <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wide ${statementType === "AIRLINE" ? "bg-blue-100 text-blue-700" : "bg-purple-100 text-purple-700"}`}>{badgeText}</span>
            <span className="text-xs font-semibold text-[#1e3a5f]">{partyText || <span className="text-red-400 italic">{isCustomer ? "Customer missing" : "Agency missing"}</span>}</span>
            <span className="text-gray-300 text-xs">·</span>
            <span className="text-xs text-gray-600">{periodText || <span className="text-red-400 italic">Dates missing</span>}</span>
            {datesText && <><span className="text-gray-300 text-xs">·</span><span className="text-xs text-gray-600">{datesText}</span></>}
            {!isStatementComplete && (
              <button
                onClick={() => setStep("drop")}
                className="ml-auto text-xs text-amber-600 underline hover:text-amber-700"
              >
                ← Fill statement details
              </button>
            )}
          </div>

          <div className="flex items-center justify-between bg-white border border-gray-200 rounded-xl px-5 py-3">
            <div className="flex items-center gap-4">
              <FileSpreadsheet className="w-5 h-5 text-green-600" />
              <div>
                <p className="text-sm font-semibold text-gray-800">{preview.file_name}</p>
                <p className="text-xs text-gray-500">{preview.total_rows} rows parsed</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setStep("mapping")}
                className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-600 hover:bg-gray-50"
              >
                Back to Mapping
              </button>
              {/* Held while the check runs, so the count on it is of the rows as they now
                  stand, not as they were before the last edit. */}
              <button
                onClick={confirmUpload}
                disabled={!isStatementComplete || nothingNew || (duplicateCheck && dupBusy)}
                title={!isStatementComplete ? "Complete statement details first" : nothingNew ? dupCheck?.reason ?? undefined : undefined}
                className="flex items-center gap-1.5 px-4 py-1.5 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {duplicateCheck && dupBusy
                  ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  : <CheckCircle className="w-3.5 h-3.5" />}
                {duplicateCheck && dupBusy
                  ? <>Checking…</>
                  : duplicateCheck && dupCheck && dupCheck.duplicates > 0
                  ? <>Confirm & Save {dupCheck.new} New Row{dupCheck.new === 1 ? "" : "s"}</>
                  : <>Confirm & Save {rows.length} Rows</>}
              </button>
            </div>
          </div>

          {duplicateCheck && (
            <DuplicateBox check={dupCheck} busy={dupBusy} error={dupError} onlyShown={onlyRows != null}
              onToggleOnly={() => setOnlyDuplicates(v => !v)} />
          )}

          {/* How the dates read in the declared format — change it here and the file is read
              again in it. */}
          {askDateFormats && datesRead.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 space-y-2">
              <p className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
                <CalendarDays className="w-4 h-4 text-gray-400" /> How your dates read
                {applyingMap && <RefreshCw className="w-3 h-3 animate-spin text-gray-400" />}
              </p>
              <DatesReadList dates={datesRead} formats={dates.formats} onChange={changeFormatOnPreview} />
              {preview.date_fix && (
                <p className="text-[11px] text-sky-700">
                  {preview.date_fix.count.toLocaleString("en-IN")} Excel date{preview.date_fix.count === 1 ? "" : "s"} read
                  as {orderLabel(dates.formats.ticket_date)} — Excel had stored {preview.date_fix.count === 1 ? "it" : "them"} with
                  day and month swapped ({preview.date_fix.columns.map(c => `${c.column} ${c.cells}`).join(", ")}).
                </p>
              )}
              {datesRead.filter(d => d.unreadable > 0).map(d => (
                <p key={d.field} className="text-[11px] text-orange-700">
                  {d.unreadable.toLocaleString("en-IN")} {d.header} value{d.unreadable === 1 ? "" : "s"} can&apos;t be read
                  as {orderLabel(d.format)}: {d.cells.slice(0, 3).map(c => `"${c.value}" (row ${c.index + 1})`).join(", ")}
                  {d.unreadable > 3 ? ", …" : ""}. If they are all like that, pick another format; otherwise set them
                  in the grid — they save empty.
                </p>
              ))}
            </div>
          )}

          {preview.warnings.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-xs text-yellow-800 space-y-1">
              {preview.warnings.map((w, i) => (
                <div key={i} className="flex items-center gap-2"><AlertCircle className="w-3.5 h-3.5 shrink-0" />{w}</div>
              ))}
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-200 px-4 py-2.5 space-y-2">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none"/>
                <input
                  type="text"
                  placeholder="Filter by ticket, sector, airline, or any value…"
                  value={filterText}
                  onChange={e=>setFilterText(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>
              {filterText&&(
                <>
                  <span className="text-[11px] text-gray-400 whitespace-nowrap">
                    {rows.filter(row=>Object.values(row).filter(v=>v!=null).join(" ").toLowerCase().includes(filterText.toLowerCase())).length} of {rows.length} rows
                  </span>
                  <button onClick={()=>setFilterText("")} title="Clear filter" className="p-1 hover:bg-gray-100 rounded-lg">
                    <X className="w-3.5 h-3.5 text-gray-500"/>
                  </button>
                </>
              )}
            </div>
            {selectedRows.size>0&&(
              <div className="flex items-center gap-2 flex-wrap border-t border-gray-100 pt-2">
                <span className="inline-flex items-center gap-1 bg-blue-100 text-blue-700 text-[11px] font-semibold px-2.5 py-1 rounded-full whitespace-nowrap">
                  ● {selectedRows.size} row{selectedRows.size!==1?"s":""} selected
                </span>
                <select
                  value={bulkColKey}
                  onChange={e=>{setBulkColKey(e.target.value);setBulkColValue("");}}
                  className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-700"
                >
                  <option value="">Column to edit…</option>
                  {TICKET_COL_GROUPS.map(g=>(
                    <optgroup key={g.label} label={g.label}>
                      {g.cols.map(c=><option key={c.key} value={c.key}>{c.label}</option>)}
                    </optgroup>
                  ))}
                </select>
                {bulkColKey&&(()=>{
                  const colType=TICKET_COL_GROUPS.flatMap(g=>g.cols).find(c=>c.key===bulkColKey)?.type??"text";
                  if(colType==="date")return(
                    <input type="date" value={bulkColValue} onChange={e=>setBulkColValue(e.target.value)}
                      className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"/>
                  );
                  if(colType==="number")return(
                    <input type="number" value={bulkColValue} onChange={e=>setBulkColValue(e.target.value)}
                      placeholder="Enter value…"
                      className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 w-28"/>
                  );
                  return(
                    <input type="text" value={bulkColValue} onChange={e=>setBulkColValue(e.target.value)}
                      placeholder="Enter value…"
                      className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 w-36"/>
                  );
                })()}
                <button
                  onClick={handleBulkApply}
                  disabled={!bulkColKey||bulkColValue===""}
                  className="px-3 py-1.5 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  Apply to {selectedRows.size} row{selectedRows.size!==1?"s":""}
                </button>
                <button
                  onClick={()=>setSelectedRows(new Set())}
                  className="px-3 py-1.5 border border-gray-200 text-gray-600 text-xs font-medium rounded-lg hover:bg-gray-50 whitespace-nowrap"
                >
                  Deselect All
                </button>
              </div>
            )}
          </div>

          <div className="bg-white rounded-lg border border-gray-200">
            <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
              <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide">Review &amp; Edit</h2>
              <span className="ml-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">{rows.length} rows</span>
              {onlyRows && (
                <span className="inline-flex items-center gap-1 text-[11px] text-amber-700 font-semibold">
                  <CopyX className="w-3 h-3" /> Showing only the {onlyRows.size} duplicate{onlyRows.size === 1 ? "" : "s"}
                  <button onClick={() => setOnlyDuplicates(false)} className="ml-1 text-gray-400 hover:text-gray-700 font-medium">
                    show all
                  </button>
                </span>
              )}
              <span className="text-[10px] text-gray-400 ml-auto">Scroll horizontally · Click any cell to edit</span>
            </div>
            <TicketReviewTable
              rows={rows}
              colGroups={TICKET_COL_GROUPS}
              onChange={handleTicketRowChange}
              onDelete={handleDeleteTicketRow}
              onAdd={handleAddTicketRow}
              filterText={filterText}
              selectedRows={selectedRows}
              onToggleRow={handleToggleRow}
              onToggleAllFiltered={handleToggleAllFiltered}
              duplicateIn={duplicateCheck ? duplicateRows : undefined}
              onlyRows={onlyRows}
            />
          </div>
        </div>
      )}

      {/* Changing a date format on the preview reads the file again — asked first when the
          grid has hand edits, which the new read replaces. */}
      {pendingFormat && (
        <ConfirmDialog
          title={`Read the file again with ${TICKET_DATE_FIELDS.find(f => f.field === pendingFormat.field)?.header ?? "the dates"} as ${orderLabel(pendingFormat.order)}?`}
          confirmLabel="Read again"
          danger={false}
          onConfirm={async () => { const p = pendingFormat; setPendingFormat(null); rereadInFormat(p.field, p.order); }}
          onClose={() => setPendingFormat(null)}
        >
          <p>The rows are read from the file again, every date in the new format. The changes you made in
            the grid are lost.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
