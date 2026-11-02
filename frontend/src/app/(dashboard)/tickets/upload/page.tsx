"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload, CheckCircle, AlertCircle, RefreshCw, ChevronLeft,
  FileSpreadsheet, X, Download, ArrowRight, ChevronDown, Trash2, Plus, Search,
  FileText, CopyX, CalendarDays, History, ArrowLeft,
} from "lucide-react";
import api from "@/lib/api";
import { useStatementSectionBase } from "@/lib/statementSection";
import StatementFormPanel, { isStatementComplete as statementComplete, type StatementType } from "@/components/tickets/StatementFormPanel";
import CustomerPartyPanel, { ALL_VENDORS_NAME, type FieldHint } from "@/components/statements/CustomerPartyPanel";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import {
  CUSTOMER_TYPE_LABEL, EMPTY_TAG, buildTagPayload, isTagComplete, type CustomerTag, type CustomerType,
} from "@/lib/customerType";
import { formatDay, formatPeriod, formatUploadedAt, uploadedAtParts } from "@/lib/statementPeriod";
import {
  type DateField, type DateFormats, type DateOrder, type DatesRead, type DetectedFormat,
  DateFormatSection, DatesReadList, orderLabel, useDateFormats,
} from "@/components/statements/dateFormat";
import ImportProgress from "@/components/tickets/ImportProgress";
import ImportReviewGrid from "@/components/tickets/ImportReviewGrid";
import { importApi, type ImportHead, type ImportJob, type ImportView } from "@/lib/ticketImport";

/** Internal Statement's declared date columns — backend services/ticket_extraction.py
 *  DATE_FORMAT_FIELDS. Doc Date follows the Ticket Date there. */
const TICKET_DATE_FIELDS: DateField[] = [
  { field: "ticket_date", header: "Booking Date" },
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
  internalMappingFields, internalReviewColGroups, mappingFieldsFor, reviewColGroups,
  STATEMENT_CATEGORY_SHORT, toInternalStandard, type StatementCategory,
  type ReviewColGroup as TColGroup, type StandardField, type TicketField,
  type TicketRow, type TicketExtractionPreview as ExtractionPreview,
} from "@/lib/ticketFields";

import { useRouter } from "next/navigation";
import Link from "next/link";

// Field metadata lives in @/lib/ticketFields so the mapping step, the review
// grid, the manual punch form and the edit modal cannot drift apart.
const TICKET_COL_GROUPS: TColGroup[] = reviewColGroups();
// Internal Statement's standard format (`standardFormat`).
const INTERNAL_COL_GROUPS: TColGroup[] = internalReviewColGroups();
const COL_TYPE: Record<string, TColGroup["cols"][number]["type"]> = Object.fromEntries(
  [...TICKET_COL_GROUPS, ...INTERNAL_COL_GROUPS].flatMap(g => g.cols).map(c => [c.key, c.type]));
const COL_LABEL: Record<string, string> = Object.fromEntries(
  [...TICKET_COL_GROUPS, ...INTERNAL_COL_GROUPS].flatMap(g => g.cols).map(c => [c.key, c.label]));
const colLabel = (key: string) => COL_LABEL[key] ?? key;

// The review grid draws a page of rows at a time: a fortnight's sales report is 30,000 lines,
// and an input per cell for all of them would stop the browser.
const REVIEW_PAGE = 100;

// ── "All vendors" (Internal Statement) ────────────────────────────────────────
// A file of every vendor's tickets: which vendor each row is, from its Supplier Name. A
// vendor is onboarded once per channel, so one supplier's GDS and LCC tickets are asked
// about apart — a GDS ticket has a numeric document number, an LCC ticket its PNR.
type SupplierLine = {
  source: string; channel: string | null;
  status: "remembered" | "matched" | "suggested" | "ambiguous" | "not_onboarded" | "blank";
  agency_id: number | null; candidates: number[]; note: string | null;
  airline_direct: boolean; airline_hint: boolean;
};
/** "agency:<id>", "airline" (bought from the airline itself — BSP, its portal), or "". */
type VendorPick = string;
const channelOf = (r: TicketRow) => (/^\d{8,}$/.test(String(r.ticket_number ?? "").replace(/[\s-]/g, "")) ? "GDS" : "LCC");
const supplierGroup = (r: TicketRow) => `${(r.supplier_name ?? "").trim()}|${channelOf(r)}`;
const SUPPLIER_STATE: Record<string, { label: string; cls: string }> = {
  remembered:    { label: "✓ saved mapping",  cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  matched:       { label: "✓ matched",        cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  suggested:     { label: "check suggestion", cls: "bg-amber-50 text-amber-700 border-amber-300" },
  ambiguous:     { label: "pick the branch",  cls: "bg-amber-50 text-amber-700 border-amber-300" },
  not_onboarded: { label: "not onboarded",    cls: "bg-red-50 text-red-700 border-red-300" },
  blank:         { label: "no supplier",      cls: "bg-gray-50 text-gray-500 border-gray-200" },
  set:           { label: "set by you",       cls: "bg-blue-50 text-blue-700 border-blue-200" },
};

// Agency options are fetched live from the supplier master API

const SKIP = "__skip__";

// ── Internal Statement: what the attached file says about itself ─────────────────
// Backend: api/v1/internal_tickets.py (/upload/guess) and services/statement_party.py.
/** A mapping remembered from an earlier statement (backend services/saved_mapping.py):
 *  `vendor` — this customer's, same columns; `vendor_changed` — this customer's, columns since
 *  changed; `layout` — another customer's statement with exactly these columns. */
type RememberedMapping = {
  match: "vendor" | "vendor_changed" | "layout";
  vendor_name: string | null;
  source_file: string | null;
  saved_at: string | null;
  fields: number;
  new_columns: string[];
  gone_columns: string[];
};

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
function DuplicateBox({ check, busy, error, onlyShown, onToggleOnly, withVendor = false }: {
  check: DuplicateCheck | null; busy: boolean; error: string | null;
  onlyShown: boolean; onToggleOnly: () => void;
  /** "All vendors" with rows left out: only the tickets with a vendor were checked. */
  withVendor?: boolean;
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
        No duplicates — none of {withVendor ? "the" : "these"} {check.total.toLocaleString("en-IN")} tickets
        {withVendor ? " with a vendor" : ""} is loaded yet, so all of them will be saved.
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
        <span>{withVendor ? "Tickets with a vendor" : "Tickets in this file"} <strong className="text-sm text-gray-800">{check.total.toLocaleString("en-IN")}</strong></span>
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

  // One page drawn at a time; the filter and the selection still span every row. A filter
  // that leaves fewer pages than the one open lands on its last.
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(filteredIndices.length / REVIEW_PAGE));
  const current = Math.min(page, pages - 1);
  const pageIndices = filteredIndices.slice(current * REVIEW_PAGE, (current + 1) * REVIEW_PAGE);

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
          ):pageIndices.map(idx=>{
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
      <div className="px-4 py-2.5 border-t border-gray-100 flex items-center gap-3 flex-wrap">
        <button onClick={onAdd} className="flex items-center gap-1.5 text-xs text-[#1e3a5f] font-medium hover:underline">
          <Plus className="w-3.5 h-3.5"/> Add row manually
        </button>
        {filteredIndices.length > REVIEW_PAGE && (
          <div className="ml-auto flex items-center gap-2 text-[11px] text-gray-500">
            <span>
              Rows {(current * REVIEW_PAGE + 1).toLocaleString("en-IN")}–{Math.min((current + 1) * REVIEW_PAGE, filteredIndices.length).toLocaleString("en-IN")}
              {" "}of {filteredIndices.length.toLocaleString("en-IN")}
            </span>
            <button onClick={() => setPage(0)} disabled={current === 0}
              className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-40">«</button>
            <button onClick={() => setPage(current - 1)} disabled={current === 0}
              className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-40">‹ Prev</button>
            <span>Page {current + 1} of {pages.toLocaleString("en-IN")}</span>
            <button onClick={() => setPage(current + 1)} disabled={current >= pages - 1}
              className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-40">Next ›</button>
            <button onClick={() => setPage(pages - 1)} disabled={current >= pages - 1}
              className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-40">»</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── The mapping remembered from an earlier statement ─────────────────────────
// Said on the mapping step in place of the name-match note — whose statement, from which
// file, and what changed since. As Third Party GDS says it (StatementUploadWizard).
function RememberedNote({ info, unused, onByName }: {
  info: RememberedMapping; unused: string[]; onByName: () => void;
}) {
  const from = [info.source_file, uploadedAtParts(info.saved_at)?.date].filter(Boolean).join(", ");
  const whose = info.vendor_name ? `${info.vendor_name}'s last statement` : "your last statement";
  const changed = info.match === "vendor_changed";
  return (
    <div className={`flex items-start gap-2 px-3 py-2 rounded-xl border text-xs ${
      changed || info.match === "layout"
        ? "border-sky-200 bg-sky-50 text-sky-800"
        : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
      <History className="w-4 h-4 shrink-0 mt-px" />
      <span className="flex-1">
        {info.match === "vendor" && (
          <><strong>Mapping remembered from {whose}</strong>{from && <> ({from})</>} —{" "}
            {info.fields} field{info.fields === 1 ? "" : "s"} mapped exactly as you saved it. Check it, then continue.</>
        )}
        {changed && (
          <><strong>The columns have changed since {whose}</strong>{from && <> ({from})</>}.{" "}
            Your mapping is kept for the columns still in the file
            {info.new_columns.length > 0 && <>; new in this file: {info.new_columns.join(", ")}</>}
            {info.gone_columns.length > 0 && <>; no longer in it: {info.gone_columns.join(", ")}</>}. Check those.</>
        )}
        {info.match === "layout" && (
          <><strong>Same columns as {info.vendor_name ? `${info.vendor_name}'s statement` : "an earlier statement"}</strong>
            {from && <> ({from})</>} — its mapping is applied. Check it, then continue.</>
        )}
        {unused.length > 0 && <> Skipped: {unused.join(", ")}.</>}
      </span>
      <button type="button" onClick={onByName} className="shrink-0 underline underline-offset-2 hover:no-underline">
        Map by column names instead
      </button>
    </div>
  );
}

// ── Internal Statement's mapping step (`standardFormat`) ─────────────────────
// Laid out as Third Party GDS's (components/statements/StatementUploadWizard.tsx), the user's
// pick: one card — the file and where it is read from, then each section two fields to a line.
// No note on where the mapping came from and no search / Auto-map / Clear all / count: the user
// had them taken out (2026-10-29). A remembered mapping is still applied, just not announced.
// A column one field takes is not offered to the others, so what a dropdown still lists is what
// is left. The column's first values show on hover, not under every field.
type MapField = TicketField & Partial<Pick<StandardField, "section" | "hint">>;

function StandardMapping({
  preview, fields, mapping, onMap, busy, onReread, onCancel, onBack, onNext, rememberMapping,
}: {
  preview: ExtractionPreview;
  fields: MapField[];
  mapping: Record<string, string>;
  onMap: (field: string, column: string) => void;
  /** Reading the file — a re-read at another sheet / header row, or the mapped read. */
  busy: boolean;
  onReread: (next: { sheet?: string; headerRow?: number }) => void;
  onCancel: () => void;
  onBack: () => void;
  onNext: () => void;
  rememberMapping: boolean;
}) {
  const columns = preview.xls_columns;
  const colOf = (key: string) => (mapping[key] && mapping[key] !== SKIP ? mapping[key] : null);

  const used = useMemo(() => new Set(Object.values(mapping).filter(c => c && c !== SKIP)), [mapping]);
  const missing = fields.filter(f => f.mapRequired && !colOf(f.key));
  // A column taken by two fields means one of them is wrong — said, not silently accepted.
  const twice = useMemo(() => {
    const seen: Record<string, string[]> = {};
    for (const f of fields) {
      const c = mapping[f.key];
      if (c && c !== SKIP) (seen[c] = seen[c] || []).push(f.mapLabel ?? f.label);
    }
    return Object.entries(seen).filter(([, fs]) => fs.length > 1);
  }, [fields, mapping]);

  // The sections, in order.
  const groups = useMemo(() => {
    const out: { title: string; fields: MapField[] }[] = [];
    for (const f of fields) {
      const title = f.section ?? "Fields";
      if (out[out.length - 1]?.title !== title) out.push({ title, fields: [] });
      out[out.length - 1].fields.push(f);
    }
    return out;
  }, [fields]);

  const samplesOf = (col: string) =>
    preview.sample_rows?.[col] ?? (preview.sample_row?.[col] ? [preview.sample_row[col]] : []);

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      {/* The file, and where in it the header is read from — shown always: a header detected
          one row out is only put right here. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3 border-b border-slate-100 bg-slate-50/60 rounded-t-xl">
        <div className="flex items-center gap-2.5 min-w-0 mr-auto">
          <FileSpreadsheet className="w-5 h-5 text-blue-600 shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-800 truncate" title={preview.file_name}>{preview.file_name}</p>
            <p className="text-[11px] text-slate-500">
              {preview.total_rows.toLocaleString("en-IN")} rows · {columns.length} columns
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-slate-500" title="Changing either reads the file again and proposes a new mapping.">
          {preview.sheet_names.length > 1 && (
            <label className="flex items-center gap-1.5">
              Sheet
              <select value={preview.sheet_name ?? ""} disabled={busy} onChange={e => onReread({ sheet: e.target.value })}
                className="border border-slate-200 rounded-lg px-2 py-1 text-xs bg-white disabled:opacity-50">
                {preview.sheet_names.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
          )}
          <label className="flex items-center gap-1.5">
            Header row
            <select value={preview.header_row} disabled={busy} onChange={e => onReread({ headerRow: Number(e.target.value) })}
              className="border border-slate-200 rounded-lg px-2 py-1 text-xs bg-white disabled:opacity-50">
              {Array.from({ length: 12 }, (_, i) => i).map(i => (
                <option key={i} value={i}>Row {i + 1}{i === preview.header_row ? " — detected" : ""}</option>
              ))}
            </select>
          </label>
        </div>
        <button onClick={onCancel} className="px-3 py-1.5 rounded-lg border border-slate-200 text-xs text-slate-600 hover:bg-white">
          Cancel
        </button>
      </div>

      <div className="p-5 space-y-3">
        {preview.preamble.length > 0 && (
          <p className="text-[11px] text-slate-500">
            <span className="font-semibold text-slate-600">Above the header:</span> {preview.preamble.slice(0, 4).join(" · ")}
          </p>
        )}

        {preview.warnings.map((w, i) => (
          <div key={i} className="flex items-start gap-2 px-3 py-2 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800">
            <AlertCircle className="w-4 h-4 shrink-0 mt-px" /> <span>{w}</span>
          </div>
        ))}
        {missing.length > 0 && (
          <div className="flex items-start gap-2 px-3 py-2 rounded-xl border border-red-200 bg-red-50 text-xs text-red-700">
            <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
            <span><strong>Still needed: {missing.map(f => f.mapLabel ?? f.label).join(", ")}.</strong> Map them to continue.</span>
          </div>
        )}
        {twice.length > 0 && (
          <div className="flex items-start gap-2 px-3 py-2 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800">
            <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
            <span>
              <strong>One column is mapped to more than one field.</strong>{" "}
              {twice.map(([col, fs]) => `“${col}” → ${fs.join(", ")}`).join("; ")}. That is allowed, but it is usually a mistake.
            </span>
          </div>
        )}

        {rememberMapping && (
          <p className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <History className="w-3 h-3 shrink-0" />
            This mapping is remembered when you save — the next file with these columns opens already mapped.
          </p>
        )}

        <div className="space-y-4 pt-1">
          {groups.map(g => (
            <div key={g.title}>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">{g.title}</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2">
                {g.fields.map(f => {
                  const col = colOf(f.key);
                  const label = f.mapLabel ?? f.label;
                  // A close name match, offered first in the list — never applied for the user.
                  const hint = !col ? preview.fuzzy_suggestions?.[f.key]?.find(s => !used.has(s.column))?.column : undefined;
                  const samples = col ? samplesOf(col) : [];
                  return (
                    <div key={f.key} className="flex items-center gap-2">
                      <label htmlFor={`map-${f.key}`} className="text-xs text-slate-600 w-44 shrink-0 truncate"
                        title={f.hint ? `${label} — ${f.hint}` : label}>
                        {label}
                        {f.mapRequired && <span className="text-red-400 ml-0.5">*</span>}
                      </label>
                      <select id={`map-${f.key}`} value={col ?? SKIP} onChange={e => onMap(f.key, e.target.value)}
                        title={col ? (samples.length ? `${col}: ${samples.join(" · ")}` : `${col}: empty in the first rows`) : undefined}
                        className={`flex-1 min-w-0 border rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                          col ? "border-slate-200 bg-white text-slate-700"
                            : f.mapRequired ? "border-red-300 bg-red-50 text-red-600"
                            : "border-slate-200 bg-white text-slate-400"}`}>
                        <option value={SKIP}>— not in file —</option>
                        {hint && <option value={hint}>{hint} (suggested)</option>}
                        {columns.filter(c => c !== hint && (c === col || !used.has(c))).map(c => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 px-5 py-3 border-t border-slate-100 bg-slate-50/60 rounded-b-xl">
        <button type="button" onClick={onBack}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-white">
          <ArrowLeft className="w-3.5 h-3.5" /> Back
        </button>
        <button type="button" onClick={onNext} disabled={busy || missing.length > 0}
          className="inline-flex items-center gap-1.5 px-5 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed">
          {busy
            ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Reading {preview.total_rows.toLocaleString("en-IN")} rows…</>
            : <>Next: preview <ArrowRight className="w-3.5 h-3.5" /></>}
        </button>
      </div>
    </div>
  );
}

// ── "All vendors": one line per Supplier Name of the file ────────────────────
// Pick a vendor once and every row of that supplier follows — the way Upload Deal's
// "All suppliers" maps each Source. A row left without one is not saved (user, 2026-10-29).
function VendorsPanel({
  counts, lines, picks, busy, agencies, unassigned, total, onPick, onShowRows,
}: {
  counts: Map<string, number>;
  lines: Record<string, SupplierLine>;
  picks: Record<string, VendorPick>;
  busy: boolean;
  agencies: AgencyOpt[];
  unassigned: number;
  total: number;
  onPick: (group: string, value: VendorPick) => void;
  onShowRows: (supplierName: string) => void;
}) {
  const label = new Map(agencies.map(a => [a.id, agencyOptionLabel(a)]));
  const groups = [...counts.entries()]
    .map(([group, count]) => ({ group, count, line: lines[group], pick: picks[group] ?? "" }))
    // What still needs a person first, then the biggest suppliers.
    .sort((a, b) => Number(!b.pick) - Number(!a.pick) || b.count - a.count);
  const [open, setOpen] = useState(true);

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className={`px-4 py-2.5 flex items-center gap-3 flex-wrap ${open ? "border-b border-gray-100" : ""}`}>
        <button type="button" onClick={() => setOpen(o => !o)} className="flex items-center gap-1.5">
          <ChevronDown className={`w-3.5 h-3.5 text-violet-700 transition-transform ${open ? "" : "-rotate-90"}`} />
          <h2 className="text-xs font-semibold text-violet-700 uppercase tracking-wide">Vendors in this file</h2>
        </button>
        <span className="text-[11px] text-gray-400">
          {groups.length} supplier{groups.length !== 1 ? "s" : ""} · {total.toLocaleString("en-IN")} rows
        </span>
        {busy ? <RefreshCw className="w-3 h-3 animate-spin text-gray-400" />
          : unassigned > 0
          ? <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-300">
              {unassigned.toLocaleString("en-IN")} row{unassigned !== 1 ? "s" : ""} without a vendor — not saved
            </span>
          : <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
              ✓ every row has a vendor
            </span>}
        <Link href="/user-master/agency-master" target="_blank" className="ml-auto text-[11px] font-semibold text-sky-600 hover:underline">
          Onboard an agency ↗
        </Link>
      </div>
      {open && (
        <div className="max-h-[320px] overflow-y-auto">
          <table className="w-full">
            <thead className="sticky top-0">
              <tr className="bg-gray-50 text-[10px] uppercase tracking-wide text-gray-500">
                <th className="px-4 py-1.5 text-left font-semibold">Supplier Name in file</th>
                <th className="px-2 py-1.5 text-right font-semibold">Rows</th>
                <th className="px-3 py-1.5 text-left font-semibold">Vendor (Agency Master)</th>
                <th className="px-2 py-1.5 text-left font-semibold">Status</th>
                <th className="px-4 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {groups.map(({ group, count, line, pick }) => {
                const [name, channel] = group.split("|");
                const auto = line?.airline_direct ? "airline" : line?.agency_id != null ? `agency:${line.agency_id}` : "";
                const state = !pick ? (line?.status ?? "not_onboarded") : pick === auto ? (line?.status ?? "set") : "set";
                const badge = SUPPLIER_STATE[state] ?? SUPPLIER_STATE.not_onboarded;
                const offered = (line?.candidates ?? []).filter(id => label.has(id));
                return (
                  <tr key={group} className={`border-t border-gray-100 align-top ${pick ? "" : "bg-amber-50/30"}`}>
                    <td className="px-4 py-1.5">
                      <span className="text-xs font-bold text-gray-800">{name || <span className="italic font-normal text-gray-400">no supplier</span>}</span>
                      <span className="ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-gray-100 text-gray-500">{channel}</span>
                    </td>
                    <td className="px-2 py-1.5 text-right text-xs text-gray-600 tabular-nums">{count.toLocaleString("en-IN")}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex items-center gap-2">
                        <select value={pick} onChange={e => onPick(group, e.target.value)}
                          className={`w-full max-w-sm border rounded-md px-2 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                            pick ? "border-gray-200 text-gray-800" : "border-amber-300 text-amber-700"}`}>
                          <option value="">— no vendor —</option>
                          <option value="airline">Bought from the airline (BSP / airline portal)</option>
                          {offered.length > 0 && (
                            <optgroup label={line?.status === "suggested" ? "Suggested" : "Possible matches"}>
                              {offered.map(id => <option key={`c${id}`} value={`agency:${id}`}>{label.get(id)}</option>)}
                            </optgroup>
                          )}
                          <optgroup label="All agencies">
                            {agencies.map(a => <option key={a.id} value={`agency:${a.id}`}>{label.get(a.id)}</option>)}
                          </optgroup>
                        </select>
                        {!pick && offered.length === 1 && (
                          <button type="button" onClick={() => onPick(group, `agency:${offered[0]}`)}
                            className="whitespace-nowrap text-[11px] font-semibold text-blue-700 hover:underline">
                            Use suggestion
                          </button>
                        )}
                        {!pick && line?.airline_hint && (
                          <button type="button" onClick={() => onPick(group, "airline")}
                            className="whitespace-nowrap text-[11px] font-semibold text-blue-700 hover:underline">
                            Bought from airline
                          </button>
                        )}
                      </div>
                      {!pick && line?.note && <p className="text-[10px] text-gray-500 mt-0.5">{line.note}</p>}
                    </td>
                    <td className="px-2 py-1.5 whitespace-nowrap" title={line?.note ?? undefined}>
                      <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold border ${badge.cls}`}>
                        {pick === "airline" ? "airline direct" : badge.label}
                      </span>
                    </td>
                    <td className="px-4 py-1.5 whitespace-nowrap text-right">
                      {name && (
                        <button type="button" onClick={() => onShowRows(name)} className="text-[11px] font-medium text-blue-600 hover:underline">
                          Show rows
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
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
  askDateFormats = false, standardFormat = false, allowAllVendors = false, defaultCustomerType = null,
  rememberMapping = false, askCategory = false, periodFromTickets = false, serverImport = false,
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
  /** Internal Statement: map onto its standard format (lib/ticketFields INTERNAL_STANDARD) —
   *  its columns, in sections, with the user's names — and review those columns. Columns
   *  left unmapped are skipped, not kept with the tickets (the server's KEEP_RAW_DATA). */
  standardFormat?: boolean;
  /** Internal Statement: B2B offers "All vendors — multi-vendor file"; the preview then asks
   *  which vendor each Supplier Name is, and every row is saved with its own. */
  allowAllVendors?: boolean;
  /** The customer type picked when the page opens (and after "Upload Another"). */
  defaultCustomerType?: CustomerType | null;
  /** Internal Statement: the column mapping a statement is saved with is remembered, and the
   *  next file with the same columns — this customer's first — opens already mapped
   *  (`${apiBase}/upload/saved-mapping`; backend services/saved_mapping.py), as Third Party
   *  GDS does. */
  rememberMapping?: boolean;
  /** Internal Statement: the details ask the Statement Type — Booking / MO (picked to start
   *  with) or Accounting — kept on the statement and written into its derived name. */
  askCategory?: boolean;
  /** Internal Statement: no Valid From / To is asked. The statement is filed under the first
   *  and last Booking Date of its tickets (backend tickets.py _booking_period), and the
   *  derived name ends with the first one once the rows are read. */
  periodFromTickets?: boolean;
  /** Internal Statement: a file of any size. It is uploaded once and its lines stay on the
   *  server — a worker reads them, the review pages through them there, and a worker saves the
   *  statement (`${apiBase}/imports`; lib/ticketImport.ts, backend services/internal_import.py).
   *  The browser never holds the rows, so a lakh-line sales report reviews like a small one. */
  serverImport?: boolean;
} = {}) {
  const isCustomer = mode === "customer";
  const startTag: CustomerTag = defaultCustomerType ? { ...EMPTY_TAG, customerType: defaultCustomerType } : EMPTY_TAG;
  const colGroups = standardFormat ? INTERNAL_COL_GROUPS : TICKET_COL_GROUPS;
  // `standardFormat`: a mapping from the server — its name match, a remembered one — knows
  // every ticket field; only those on the screen may take a column (lib/ticketFields).
  const fitMapping = (m: Record<string, string>) => (standardFormat ? toInternalStandard(m) : m);
  const sectionBase = useStatementSectionBase();
  const router = useRouter();

  // "processing": `serverImport` — the worker is reading the file for the review.
  type Step = "drop" | "mapping" | "processing" | "preview" | "saving" | "done";
  const [step,           setStep]           = useState<Step>("drop");
  const [preview,        setPreview]        = useState<ExtractionPreview | null>(null);
  const [storedFile,     setStoredFile]     = useState<File | null>(null);
  const [mapping,        setMapping]        = useState<Record<string, string>>({});
  // `rememberMapping`: the name-matched mapping of the columns (what "Map by column names
  // instead" goes back to), the remembered one the mapping step opened with, and whether the
  // user has changed the mapping since — a mapping they edited is never replaced.
  const [nameMapping,    setNameMapping]    = useState<Record<string, string>>({});
  const [remembered,     setRemembered]     = useState<RememberedMapping | null>(null);
  const [mappingEdited,  setMappingEdited]  = useState(false);
  const [proposing,      setProposing]      = useState(false);
  const [applyingMap,    setApplyingMap]    = useState(false);
  const [parsing,        setParsing]        = useState(false);
  const [downloading,    setDownloading]    = useState(false);
  const [error,          setError]          = useState<string | null>(null);
  const [batchId,        setBatchId]        = useState<string | null>(null);
  const [rows,           setRows]           = useState<TicketRow[]>([]);
  // The grid was changed by hand since the file was last read — re-reading it would drop that.
  const [rowsEdited,     setRowsEdited]     = useState(false);
  const downloadLinkRef  = useRef<HTMLAnchorElement>(null);

  // ── `serverImport`: the upload kept on the server ─────────────────────────
  // `job` is the import as the server last said — its worker's progress, and under review the
  // summary above the grid (counted off the lines there, edits included). `rows` stays empty.
  const imports = useMemo(() => importApi(apiBase), [apiBase]);
  const [importId,   setImportId]   = useState<string | null>(null);
  const [job,        setJob]        = useState<ImportJob | null>(null);
  const [gridView,   setGridView]   = useState<ImportView>("all");
  const [gridSearch, setGridSearch] = useState("");
  const [gridReload, setGridReload] = useState(0);
  const summary = serverImport ? job?.summary ?? null : null;

  // ── Statement form state ───────────────────────────────────────────────────
  const [statementType, setStatementType] = useState<StatementType>("B2B");
  const [agency,        setAgency]        = useState("");
  // Customer mode only: WHO the tickets were sold to.
  const [tag,           setTag]           = useState<CustomerTag>(startTag);
  // "All vendors — multi-vendor file" (`allowAllVendors`): B2B with no one agency.
  const [multiVendor,   setMultiVendor]   = useState(false);
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

  // `askCategory`: Booking / MO unless the user picks Accounting.
  const [category, setCategory] = useState<StatementCategory>("booking");

  // Customer mode is gated on the customer tag; internal mode on the vendor agency.
  // `periodFromTickets`: no period to give — the tickets' booking dates are it.
  const allVendors = allowAllVendors && multiVendor && tag.customerType === "agency";
  const periodGiven = periodFromTickets || (validFrom !== "" && validTo !== "" && validTo >= validFrom);
  const isStatementComplete = (isCustomer
    ? ((allVendors || isTagComplete(tag)) && periodGiven)
    : statementComplete(agency, validFrom, validTo)) && dates.complete;

  // ── Internal Statement: duplicates (`duplicateCheck`) ──────────────────────
  const [dupCheck,      setDupCheck]      = useState<DuplicateCheck | null>(null);
  const [dupBusy,       setDupBusy]       = useState(false);
  const [dupError,      setDupError]      = useState<string | null>(null);
  const dupSeq = useRef(0);
  const [savedReport,   setSavedReport]   = useState<{
    created: number; duplicates: DuplicateReport | null;
    /** "All vendors": rows left out for having no vendor. */
    noVendor: number;
  } | null>(null);

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

  // ── Editable row handlers ─────────────────────────────────────────────────
  const handleTicketRowChange = useCallback((idx: number, key: string, val: string) => {
    setRowsEdited(true);
    setRows(prev => prev.map((r, i) => {
      if (i !== idx) return r;
      return { ...r, [key]: COL_TYPE[key] === "number" ? (val === "" ? null : parseFloat(val)) : (val || null) };
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
    setRowsEdited(true);
    setRows(prev => prev.map((r, i) => {
      if (!selectedRows.has(i)) return r;
      return { ...r, [bulkColKey]: COL_TYPE[bulkColKey] === "number" ? (bulkColValue === "" ? null : parseFloat(bulkColValue)) : (bulkColValue || null) };
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
      // A read only for the columns (the drop, a sheet or header-row change): no screen
      // takes rows from it, so none are built or sent.
      columnsOnly?: boolean;
    } = {},
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("statement_type", statementType);
    if (opts.columnsOnly) form.append("include_rows", "false");
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
    // `serverImport`: the upload's own answer carries the date format (`takeHead`).
    if (serverImport || !askDateFormats || !storedFile || !hasPreview) return;
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
  }, [serverImport, askDateFormats, storedFile, hasPreview, sheet, headerRow, detectPeriod, apiBase]);

  /** `serverImport`: what the server read off the stored file — its columns, as /upload/extract
   *  gives them, and how it writes its dates, as /upload/detect-date-formats does. One read. */
  const takeHead = (head: ImportHead, file: File) => {
    setImportId(head.import_id);
    setDetected({ file, byField: Object.fromEntries(head.date_formats.fields.map(d => [d.field, d])) });
    return head.preview;
  };
  /** The import a new file or a fresh start leaves behind — its lines and its stored file. */
  const dropImport = () => {
    if (serverImport && importId && job?.status !== "saved") void imports.discard(importId).catch(() => {});
    setImportId(null); setJob(null); setGridView("all"); setGridSearch("");
  };

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

    // `periodFromTickets`: no period is asked, so none is filled in — only the customer below.
    const period = g?.period ?? null;
    const typedDates = !periodGuessed && !!(validFrom || validTo);
    if (periodFromTickets) {
      setPeriodHint(null);
    } else if (!typedDates) {
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
    // "All vendors" is the user's answer too — a name read off the file names one of them.
    if (allVendors) return;
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
      const data = serverImport
        ? takeHead(await imports.create(files[0]), files[0])
        : await runExtract(files[0], { columnsOnly: true });
      setPreview(data);
      setMapping(fitMapping(data.suggested_mapping ?? {}));
      setNameMapping(fitMapping(data.suggested_mapping ?? {}));
      setRemembered(null);
      setMappingEdited(false);
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
    dropImport();
    setPreview(null); setStoredFile(null); setMapping({}); setSheet(null); setHeaderRow(null);
    setDupCheck(null); setRows([]);
    setNameMapping({}); setRemembered(null); setMappingEdited(false);
  };

  /** `rememberMapping`: the mapping a statement with these columns was saved with — this
   *  customer's first — in place of the name match, unless the user has edited the mapping.
   *  Asked once the customer is settled; on any failure the name match stays. `fresh`: the
   *  columns were just read again, so the user's edits (of the old ones) do not hold it back. */
  const proposeMapping = async (columns: string[], byName: Record<string, string>, fresh = false) => {
    if (!rememberMapping || (mappingEdited && !fresh)) return;
    setProposing(true);
    try {
      const { data } = await api.post<{ mapping: Record<string, string>; remembered: RememberedMapping | null }>(
        `${apiBase}/upload/saved-mapping`,
        { columns, by_name: byName, ...(allVendors ? { multi_vendor: true } : buildTagPayload(tag)) },
      );
      setMapping(fitMapping(data.mapping));
      setRemembered(data.remembered);
    } catch {
      setMapping(byName);
      setRemembered(null);
    } finally {
      setProposing(false);
    }
  };

  /** "Next: map columns" (`fillFromFile`): once the details — the date format included — are
   *  complete. The panel and the date format box say what is missing. */
  const startNext = async () => {
    setFormTouched(true);
    if (!isStatementComplete) return;
    setError(null);
    if (preview) await proposeMapping(preview.xls_columns, nameMapping);
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
      if (serverImport && importId) {
        // The worker reads every line; the page follows it until the review is ready.
        const columnMap = Object.fromEntries(Object.entries(mapping).filter(([, c]) => c && c !== SKIP));
        setJob(await imports.parse(importId, columnMap, askDateFormats ? (formats ?? dates.formats) : null));
        setGridView("all");
        setGridSearch("");
        setStep("processing");
        return;
      }
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
      const data = serverImport && importId
        ? takeHead(await imports.reread(importId, nextSheet, nextHeader), storedFile)
        : await runExtract(storedFile, { sheet: nextSheet, headerRow: nextHeader, columnsOnly: true });
      setPreview(data);
      setMapping(fitMapping(data.suggested_mapping ?? {}));
      setNameMapping(fitMapping(data.suggested_mapping ?? {}));
      setRemembered(null);
      setMappingEdited(false);
      setSheet(data.sheet_name ?? null);
      setHeaderRow(data.header_row ?? 0);
      // New columns: the edits named the old ones, so a remembered mapping is asked for afresh.
      await proposeMapping(data.xls_columns, fitMapping(data.suggested_mapping ?? {}), true);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to re-read the file.");
    } finally {
      setApplyingMap(false);
    }
  };

  // Duplicate rows → where the ticket already is, for the grid. `onlyDuplicates` narrows the
  // grid to them, falling back to every row once none is left — so fixing the last one does
  // not empty it.
  const duplicateRows = useMemo(() => {
    const out = new Map<number, string>();
    for (const d of dupCheck?.rows ?? []) out.set(d.index, duplicateOf(d, dupCheck?.statements ?? []));
    return out;
  }, [dupCheck]);
  // `serverImport`: the duplicates as the server counts them, off the lines not removed.
  const dupShown: DuplicateCheck | null = serverImport ? summary?.duplicates ?? null : dupCheck;
  const nothingNew = duplicateCheck && dupShown != null && !dupShown.can_save;
  const [onlyDuplicates, setOnlyDuplicates] = useState(false);
  const onlyRows = useMemo(
    () => (onlyDuplicates && duplicateRows.size > 0 ? new Set(duplicateRows.keys()) : null),
    [onlyDuplicates, duplicateRows]);

  const activeFields: (TicketField & Partial<Pick<StandardField, "section" | "hint">>)[] = useMemo(
    () => (standardFormat ? internalMappingFields() : mappingFieldsFor(statementType)), [standardFormat, statementType]);
  const requiredKeys    = activeFields.filter(f => f.mapRequired).map(f => f.key);
  // The file's columns no field takes — off the mapping as it stands (a remembered one, or
  // the user's edits), not the name match the file was first read with.
  const unmappedColumns = useMemo(() => {
    const used = new Set(Object.values(mapping).filter(c => c && c !== SKIP));
    return (preview?.xls_columns ?? []).filter(c => !used.has(c));
  }, [mapping, preview]);

  // The review grid's columns: on the standard format, only those this file filled — a
  // Yatra report and a consolidator's ticket statement each see their own.
  // `serverImport`: the fields the worker found filled.
  const filledOnServer = serverImport ? job?.read.filled : undefined;
  const reviewGroups = useMemo(() => {
    if (!standardFormat) return colGroups;
    const filled = new Set<string>(filledOnServer ?? []);
    const keys = colGroups.flatMap(g => g.cols.map(c => c.key));
    for (const r of filledOnServer ? [] : rows) {
      for (const k of keys) {
        const v = (r as Record<string, unknown>)[k];
        if (v != null && v !== "") filled.add(k);
      }
      if (filled.size === keys.length) break;
    }
    return colGroups
      .map(g => ({ ...g, cols: g.cols.filter(c => filled.has(c.key) || (!!mapping[c.key] && mapping[c.key] !== SKIP)) }))
      .filter(g => g.cols.length > 0);
  }, [standardFormat, colGroups, rows, mapping, filledOnServer]);

  // ── "All vendors": which vendor each Supplier Name is ─────────────────────
  // Asked once per supplier and channel whenever the set of them changes; what the
  // reviewer picks is kept across re-reads of the file.
  const supplierCounts = useMemo(() => {
    const out = new Map<string, number>();
    if (!allVendors) return out;
    // `serverImport`: counted on the server, by the same "<Supplier Name>|GDS" group.
    if (summary) {
      for (const s of summary.suppliers) out.set(s.group, s.count);
      return out;
    }
    for (const r of rows) out.set(supplierGroup(r), (out.get(supplierGroup(r)) ?? 0) + 1);
    return out;
  }, [allVendors, rows, summary]);
  const supplierKey = [...supplierCounts.keys()].sort().join("\n");
  const [supplierLines, setSupplierLines] = useState<Record<string, SupplierLine>>({});
  const [vendorPick, setVendorPick] = useState<Record<string, VendorPick>>({});
  const [suppliersBusy, setSuppliersBusy] = useState(false);
  const [airlineIds, setAirlineIds] = useState<Map<string, number>>(new Map());
  useEffect(() => {
    if (!allVendors || step !== "preview" || !supplierKey) return;
    const groups = supplierKey.split("\n");
    let live = true;
    setSuppliersBusy(true);
    api.post<{ suppliers: SupplierLine[] }>(`${apiBase}/upload/suppliers`, {
      suppliers: groups.map(g => { const [name, channel] = g.split("|"); return { name: name || "", channel }; }),
    })
      .then(({ data }) => {
        if (!live) return;
        const lines = Object.fromEntries(groups.map((g, i) => [g, data.suppliers[i]]));
        setSupplierLines(lines);
        // Pre-picked only where it is certain — a saved choice, or one exact match.
        setVendorPick(prev => {
          const next = { ...prev };
          for (const g of groups) {
            if (next[g] !== undefined) continue;
            const l = lines[g];
            next[g] = l?.airline_direct ? "airline" : l?.agency_id != null ? `agency:${l.agency_id}` : "";
          }
          return next;
        });
      })
      .catch(() => { if (live) setSupplierLines({}); })
      .finally(() => { if (live) setSuppliersBusy(false); });
    return () => { live = false; };
  }, [allVendors, step, supplierKey, apiBase]);
  // "Bought from the airline": the row's own airline, in the airline master by its code.
  useEffect(() => {
    if (!allVendors || airlineIds.size) return;
    api.get<{ id: number; iata_code: string | null; is_active: boolean }[]>("/airlines/", { params: { limit: 5000 } })
      .then(({ data }) => setAirlineIds(new Map(
        data.filter(a => a.is_active && a.iata_code).map(a => [a.iata_code!.trim().toUpperCase(), a.id]))))
      .catch(() => {});
  }, [allVendors, airlineIds.size]);
  const payableFor = useCallback((r: TicketRow): Partial<TicketRow> => {
    const pick = vendorPick[supplierGroup(r)] ?? "";
    if (pick.startsWith("agency:")) return { payable_type: "b2b", payable_agency_id: Number(pick.slice(7)) };
    if (pick === "airline") {
      const id = airlineIds.get(String(r.airlines_code ?? "").trim().toUpperCase());
      if (id != null) return { payable_type: "airline", payable_airline_id: id };
    }
    return {};
  }, [vendorPick, airlineIds]);
  // "All vendors": only the rows with a vendor are saved (user, 2026-10-29) — a supplier left on
  // "no vendor", or "bought from the airline" with an airline not in the master, is left out.
  // `saveIdx`: the grid positions of the rows a save sends, in order.
  const saveIdx = useMemo(() => {
    const out: number[] = [];
    rows.forEach((r, i) => { if (!allVendors || payableFor(r).payable_type) out.push(i); });
    return out;
  }, [allVendors, rows, payableFor]);
  // `serverImport`: the lines are counted by supplier, not held — a supplier with a vendor picked
  // saves its lines ("bought from the airline" lines whose airline is not in the master are
  // left out by the save, and the done screen counts them).
  const totalRows = serverImport ? (summary?.kept ?? 0) : rows.length;
  const saveCount = useMemo(() => {
    if (!serverImport) return saveIdx.length;
    if (!allVendors) return summary?.kept ?? 0;
    let n = 0;
    for (const [group, count] of supplierCounts) if (vendorPick[group]) n += count;
    return n;
  }, [serverImport, saveIdx, allVendors, summary, supplierCounts, vendorPick]);
  const rowsWithoutVendor = totalRows - saveCount;
  const noVendorAtAll = allVendors && totalRows > 0 && saveCount === 0;

  // `periodFromTickets`: the first and last Booking Date of the rows a save sends (a row's Doc
  // Date where it has none) — what the server files the statement under. None before the rows
  // are read. Not every row read: "All vendors" saves only the rows with a vendor.
  const ticketPeriod = useMemo(() => {
    if (!periodFromTickets) return null;
    // `serverImport`: of the lines not removed.
    if (serverImport) return summary?.period ?? null;
    let from: string | null = null;
    let to: string | null = null;
    for (const i of saveIdx) {
      const r = rows[i];
      const v = String(r.ticket_date || r.doc_date || "");
      if (!ISO_DAY.test(v)) continue;
      const d = v.slice(0, 10);
      if (from == null || d < from) from = d;
      if (to == null || d > to) to = d;
    }
    return from && to ? { from, to } : null;
  }, [periodFromTickets, rows, saveIdx, serverImport, summary]);

  // "B2B - Globe Air Travels - 2026-08-01" — the name the server would give a blank one,
  // shown filled in so the user sees it before saving. `periodFromTickets`:
  // "B2B - All vendors - Booking/MO - 2026-10-01", the date added once the rows are read.
  useEffect(() => {
    if (!fillFromFile || !nameAuto) return;
    const t = tag.customerType;
    if (periodFromTickets) {
      setStatementName(t && tag.partyName
        ? [CUSTOMER_TYPE_LABEL[t], tag.partyName, askCategory ? STATEMENT_CATEGORY_SHORT[category] : "", ticketPeriod?.from ?? ""]
            .filter(Boolean).join(" - ")
        : "");
      return;
    }
    setStatementName(t && tag.partyName && validFrom ? `${CUSTOMER_TYPE_LABEL[t]} - ${tag.partyName} - ${validFrom}` : "");
  }, [fillFromFile, nameAuto, tag.customerType, tag.partyName, validFrom, periodFromTickets, askCategory, category, ticketPeriod]);

  // Asked again after every edit, add and delete — a corrected ticket number, passenger, date
  // or amount can turn a duplicate into a new ticket, and row positions move — and, on "All
  // vendors", after every vendor picked: only the rows a save sends are checked, so the counts
  // are of what is saved. The answer's positions are put back to the grid's. Who the tickets
  // were sold to and the period do not enter into it.
  useEffect(() => {
    // `serverImport`: the worker keyed every line, and each edit is checked as it is saved.
    if (serverImport || !duplicateCheck || step !== "preview" || rows.length === 0) return;
    // The vendor picks are still being read: the save set is not known yet.
    if (allVendors && suppliersBusy) return;
    const seq = ++dupSeq.current;
    if (saveIdx.length === 0) { setDupCheck(null); setDupError(null); setDupBusy(false); return; }
    setDupBusy(true);
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.post<DuplicateCheck>(`${apiBase}/upload/duplicates`, {
          // The source cells are not compared, so they are not sent (undefined drops out of JSON).
          rows: saveIdx.map(i => ({ ...rows[i], raw_data: undefined })),
        });
        if (seq !== dupSeq.current) return;
        const at = (k: number) => saveIdx[k] ?? k;
        setDupCheck({
          ...data,
          rows: data.rows.map(d => ({ ...d, index: at(d.index) })),
          lines: data.lines.map(d => ({ ...d, index: at(d.index) })),
        });
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
  }, [serverImport, duplicateCheck, step, rows, apiBase, allVendors, suppliersBusy, saveIdx]);
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
  // `serverImport`: the same, counted on the server.
  const serverDatesRead: DatesRead[] = useMemo(() => !summary ? [] : dateFields.map((f) => {
    const d = summary.dates.find(x => x.field === f.field);
    const isMapped = (k: string) => !!mapping[k] && mapping[k] !== SKIP;
    return { ...f, header: d?.key === "doc_date" ? "Doc Date" : f.header,
      format: dates.formats[f.field] ?? null, read: d?.read ?? 0, first: d?.first ?? null, last: d?.last ?? null,
      unreadable: d?.unreadable ?? 0, cells: d?.cells ?? [],
      mapped: isMapped(f.field) || (f.field === "ticket_date" && isMapped("doc_date")) };
  }), [summary, dateFields, mapping, dates.formats]);
  const datesShown = serverImport ? serverDatesRead : datesRead;

  // Changing a format on the preview reads the file again in it; hand edits are asked about first.
  const [pendingFormat, setPendingFormat] = useState<{ field: string; order: DateOrder } | null>(null);
  const rereadInFormat = (field: string, order: DateOrder) => {
    dates.choose(field, order);
    void applyMapping({ ...dates.formats, [field]: order });
  };
  const changeFormatOnPreview = (field: string, order: DateOrder) => {
    if (dates.formats[field] === order) return;
    if (serverImport ? (summary?.edited ?? 0) > 0 : rowsEdited) setPendingFormat({ field, order });
    else rereadInFormat(field, order);
  };
  const datesText = askDateFormats && dates.complete
    ? `Dates ${dateFields.map(f => orderLabel(dates.formats[f.field])).join(" / ")}` : "";

  // ── Step 3: confirm → save ────────────────────────────────────────────────
  const confirmUpload = async () => {
    setFormTouched(true);
    if (!isStatementComplete || !preview) return;
    if (serverImport && importId) {
      // The statement details; the worker saves the lines the server holds.
      setError(null);
      try {
        setJob(await imports.save(importId, {
          statement_name: statementName.trim() || null,
          ...(askCategory ? { statement_category: category } : {}),
          agency: tag.partyName || null,
          ...(allVendors ? { multi_vendor: true, vendor_picks: vendorPick } : buildTagPayload(tag)),
        }));
        setStep("saving");
      } catch (e: unknown) {
        setError(apiDetail(e) ?? "Failed to save tickets.");
      }
      return;
    }
    setStep("saving");
    setError(null);
    try {
      const { data } = await api.post<{ batch_id: string; created_count: number; duplicates?: DuplicateReport | null }>(
        `${apiBase}/upload/confirm`,
        {
          file_name:      preview.file_name,
          // "All vendors": the rows with a vendor, each carrying the one picked for its Supplier Name.
          rows: allVendors ? saveIdx.map(i => ({ ...rows[i], ...payableFor(rows[i]) })) : rows,
          // A customer statement is always B2B-shaped: the airline field set
          // belongs to a vendor file, and those go through Vendors → Statements.
          statement_type: isCustomer ? "B2B" : statementType,
          // Name for display, id for billing. Without the id, two branches of one
          // vendor both match this statement and neither can safely bill it.
          // In customer mode the server re-derives both from the authorised party.
          agency: isCustomer ? (tag.partyName || "—") : (selectedAgency?.name ?? agency),
          agency_id: isCustomer ? null : (selectedAgency?.id ?? null),
          ...(isCustomer ? (allVendors ? { multi_vendor: true } : buildTagPayload(tag)) : {}),
          statement_name: statementName.trim() || null,
          // `periodFromTickets`: none sent — the server files it under the tickets' booking dates.
          ...(periodFromTickets ? {} : { valid_from: validFrom, valid_to: validTo }),
          ...(askCategory ? { statement_category: category } : {}),
          // How the rows' dates were read — kept on the statement (Internal Statement).
          ...(askDateFormats ? { date_formats: dates.formats } : {}),
          // The columns and how they were mapped — remembered for the next file like it.
          ...(rememberMapping ? {
            columns: preview.xls_columns,
            column_map: Object.fromEntries(Object.entries(mapping).filter(([, c]) => c && c !== SKIP)),
          } : {}),
        },
      );
      setBatchId(data.batch_id);
      setSavedReport({ created: data.created_count, duplicates: data.duplicates ?? null, noVendor: rowsWithoutVendor });
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

  // ── `serverImport`: following the worker ──────────────────────────────────
  // Polled while it reads or saves; the review opens when the read is through, the done screen
  // when the save is. A save that failed is back under review, with its reason.
  const jobStatus = job?.status;
  useEffect(() => {
    if (!serverImport || !importId || (jobStatus !== "parsing" && jobStatus !== "saving")) return;
    let live = true;
    const timer = setInterval(async () => {
      try {
        const next = await imports.get(importId);
        if (live) setJob(next);
      } catch { /* keep polling */ }
    }, 1500);
    return () => { live = false; clearInterval(timer); };
  }, [serverImport, importId, jobStatus, imports]);
  useEffect(() => {
    if (!serverImport || !job) return;
    if (step === "processing" && job.status === "ready") {
      setGridReload(n => n + 1);
      setStep("preview");
    } else if (step === "processing" && job.status === "failed") {
      setError(job.error ?? "The file could not be read.");
      setStep("mapping");
    } else if (step === "saving" && job.status === "saved" && job.result) {
      setBatchId(job.result.batch_id);
      setSavedReport({ created: job.result.created_count, duplicates: job.result.duplicates ?? null,
        noVendor: job.result.no_vendor });
      setStep("done");
    } else if (step === "saving" && job.status === "ready") {
      setError(job.error ?? "The statement could not be saved.");
      setStep("preview");
    }
  }, [serverImport, job, step]);
  // A line edited, removed or added, or a vendor picked: the summary above the grid is counted
  // again, once the changes stop. "All vendors": its duplicates among the lines a save sends —
  // the suppliers given a vendor — as the page counted them before (user, 2026-10-29).
  const pickedGroups = useMemo(
    () => (allVendors ? Object.keys(vendorPick).filter(g => vendorPick[g]) : null), [allVendors, vendorPick]);
  const pickedRef = useRef(pickedGroups);
  pickedRef.current = pickedGroups;
  const refreshSeq = useRef(0);
  // The summary is being counted again: the Save button's count is about to change.
  const [recounting, setRecounting] = useState(false);
  const refreshJob = useCallback(() => {
    if (!importId) return;
    const n = ++refreshSeq.current;
    setRecounting(true);
    setTimeout(async () => {
      if (n !== refreshSeq.current) return;
      try {
        const next = await imports.summary(importId, pickedRef.current);
        if (n === refreshSeq.current) setJob(next);
      } catch { /* the next edit asks again */ }
      finally {
        if (n === refreshSeq.current) setRecounting(false);
      }
    }, 700);
  }, [importId, imports]);
  const pickedKey = (pickedGroups ?? []).join("\n");
  useEffect(() => {
    if (serverImport && allVendors && step === "preview") refreshJob();
  }, [serverImport, allVendors, step, pickedKey, refreshJob]);
  const duplicateLabel = useCallback(
    (batchId: string) => duplicateOf({ batch_id: batchId }, summary?.duplicates.statements ?? []), [summary]);
  const showError = useCallback((m: string) => setError(m), []);

  const reset = () => {
    dropImport();
    setStep("drop"); setPreview(null); setStoredFile(null);
    setMapping({}); setBatchId(null); setError(null); setRows([]); resetFilter();
    setStatementType("B2B"); setAgency(""); setStatementName("");
    setValidFrom(""); setValidTo(""); setFormTouched(false); setCategory("booking");
    // The customer too — "Upload Another" is a new statement, and a kept customer would
    // stop the next file's own customer being read off it.
    setTag(startTag); setMultiVendor(false); setSheet(null); setHeaderRow(null);
    setSupplierLines({}); setVendorPick({});
    setNameMapping({}); setRemembered(null); setMappingEdited(false);
    setTagGuessed(false); setPeriodGuessed(false); setNameAuto(true);
    setPartyHint(null); setPeriodHint(null);
    setDupCheck(null); setDupError(null); setSavedReport(null); setOnlyDuplicates(false);
    dates.reset(); setDetected(null); setRowsEdited(false);
  };

  // What the summary bars and the done screen say the statement is: the CUSTOMER in
  // customer mode (it used to read the vendor-mode `agency`, which this mode never sets).
  const badgeText = isCustomer ? (tag.customerType ? CUSTOMER_TYPE_LABEL[tag.customerType] : "—") : statementType;
  const partyText = isCustomer
    ? (allVendors ? ALL_VENDORS_NAME : tag.partyName || (tag.customerType === "direct" ? "Walk-in customer" : ""))
    : agency;
  const periodText = periodFromTickets
    ? (ticketPeriod ? `Booked ${formatPeriod(ticketPeriod.from, ticketPeriod.to)}` : "")
    : validFrom && validTo ? (isCustomer ? formatPeriod(validFrom, validTo) : `${validFrom} – ${validTo}`) : "";
  const categoryText = askCategory ? STATEMENT_CATEGORY_SHORT[category] : "";

  const isDone = step === "done";
  // What the read said beyond its rows — the worker's read, on `serverImport`.
  const readWarnings = serverImport ? job?.read.warnings ?? [] : preview?.warnings ?? [];
  const dateFix = serverImport ? job?.read.date_fix ?? null : preview?.date_fix ?? null;
  const tooLong = summary?.too_long ?? 0;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      <a ref={downloadLinkRef} className="hidden" />

      {/* page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {/* Back to the section the upload belongs to — Internal Statement → Statements there. */}
          <Link href={listHref ?? "/customers/statements"} aria-label="Back to statements"
            className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
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
              const labels: Record<Step, string> = { drop: "Upload", mapping: "Map Columns", processing: "Reading", preview: "Preview", saving: "Saving", done: "Done" };
              // The worker reading the file is the way into the preview.
              const at      = step === "processing" ? "preview" : step;
              const active  = at === s;
              const passed  = ["drop", "mapping", "preview", "saving", "done"].indexOf(at) > i;
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
              {[categoryText, periodText].filter(Boolean).join(" · ")}
            </p>
            <p className="text-sm text-gray-500 mt-2">
              {(savedReport?.created ?? rows.length).toLocaleString("en-IN")} tickets saved from <span className="font-medium">{preview.file_name}</span>
            </p>
            {!!savedReport?.noVendor && (
              <p className="text-xs text-amber-700 mt-1.5">
                {savedReport.noVendor.toLocaleString("en-IN")} row{savedReport.noVendor === 1 ? "" : "s"} without a vendor
                {savedReport.noVendor === 1 ? " was" : " were"} not saved.
              </p>
            )}
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
      {step === "saving" && serverImport && job && (
        <ImportProgress job={job} title="Saving the statement"
          note="Saving runs on the server. If you leave this page, the statement still appears under Statements when it is done." />
      )}
      {step === "saving" && !serverImport && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center space-y-3">
            <RefreshCw className="w-8 h-8 text-blue-500 animate-spin mx-auto" />
            <p className="text-sm text-gray-600">Saving statement and tickets to database…</p>
          </div>
        </div>
      )}

      {/* ── `serverImport`: the worker reading the file for the review ──────── */}
      {step === "processing" && job && (
        <ImportProgress job={job} title="Reading the file for review"
          note="Keep this page open — the review opens here when the file has been read."
          onBack={() => setStep("mapping")} backLabel="Back to mapping" />
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
              nameHint={!(fillFromFile && nameAuto && statementName) ? null
                : !periodFromTickets ? "Filled in from the customer and the period — type your own to change it."
                : ticketPeriod ? "Filled in from the customer, the statement type and the first booking date — type your own to change it."
                : "Filled in from the customer and the statement type; the first booking date is added once the rows are read. Type your own to change it."}
              allowAllVendors={allowAllVendors}
              multiVendor={multiVendor}
              setMultiVendor={(v) => { setMultiVendor(v); if (v) { setTagGuessed(false); setPartyHint(null); } }}
              askPeriod={!periodFromTickets}
              {...(askCategory ? { category, setCategory } : {})}
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
                    Check the statement details on the left — the customer{periodFromTickets ? "" : ", the period"} and the name are filled in
                    from the file wherever it says them{askDateFormats ? ", and the date format from how its dates are written" : ""}.
                    Change anything that is wrong, then press Next to map the columns.
                  </p>
                  <div className="flex justify-end">
                    <button onClick={() => void startNext()} disabled={proposing}
                      className="flex items-center gap-1.5 px-5 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f] disabled:opacity-50">
                      {proposing
                        ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Opening the mapping…</>
                        : <>Next: map columns <ArrowRight className="w-3.5 h-3.5" /></>}
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
            {categoryText && <><span className="text-gray-300 text-xs">·</span><span className="text-xs text-gray-600">{categoryText}</span></>}
            {/* `periodFromTickets`: the booking dates, once the rows are read — nothing to miss before. */}
            {(periodText || !periodFromTickets) && <>
              <span className="text-gray-300 text-xs">·</span>
              <span className="text-xs text-gray-600">{periodText || <span className="text-red-400 italic">Dates missing</span>}</span>
            </>}
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

          {standardFormat ? (
            <StandardMapping
              preview={preview} fields={activeFields} mapping={mapping}
              onMap={(field, col) => { setMappingEdited(true); setMapping(prev => ({ ...prev, [field]: col })); }}
              busy={applyingMap} onReread={(next) => void reread(next)}
              onCancel={reset} onBack={() => setStep("drop")} onNext={() => void applyMapping()}
              rememberMapping={rememberMapping}
            />
          ) : (<>
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

          {remembered ? (
            <RememberedNote info={remembered} unused={unmappedColumns}
              onByName={() => { setMapping(nameMapping); setRemembered(null); setMappingEdited(true); }} />
          ) : preview.is_template_match ? (
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

            {unmappedColumns.length > 0 && (
              <p className="text-[11px] text-amber-700">
                <span className="font-semibold">
                  {unmappedColumns.length} column{unmappedColumns.length === 1 ? "" : "s"} in
                  your file {unmappedColumns.length === 1 ? "is" : "are"} not mapped:
                </span>{" "}
                {unmappedColumns.join(", ")}.{" "}
                {standardFormat
                  ? "They are skipped — not saved with the tickets. The file itself is kept with the statement."
                  : "Their values are still saved with the ticket, but nothing reports on them until they are mapped below."}
              </p>
            )}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/50 flex items-center justify-between gap-3 flex-wrap">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Column Mapping</p>
              {rememberMapping ? (
                <p className="flex items-center gap-1.5 text-[11px] text-gray-400">
                  <History className="w-3 h-3 shrink-0" />
                  This mapping is remembered when you save — the next file with these columns opens already mapped.
                </p>
              ) : (
                <p className="text-xs text-gray-400">Select which column from your file maps to each field</p>
              )}
            </div>
            <div className="divide-y divide-gray-100 max-h-[460px] overflow-y-auto">
              {activeFields.map((field, fi) => {
                const mapped    = mapping[field.key];
                const isSkipped = !mapped || mapped === SKIP;
                // The standard format in its sections — a heading where each one starts.
                const sectionStart = field.section && field.section !== activeFields[fi - 1]?.section;
                return (
                  <Fragment key={field.key}>
                  {sectionStart && (
                    <div className="px-5 py-1.5 bg-[#1e3a5f]/5 text-[10px] font-bold text-[#1e3a5f] uppercase tracking-wider">
                      {field.section}
                    </div>
                  )}
                  <div className="flex items-center px-5 py-2.5 gap-4">
                    <div className="w-56 shrink-0">
                      <span className="text-xs font-medium text-gray-700">{field.mapLabel ?? field.label}</span>
                      {field.mapRequired && <span className="text-red-500 ml-0.5 text-xs">*</span>}
                      {field.hint && <span className="block text-[10px] text-gray-400 leading-tight mt-0.5">{field.hint}</span>}
                    </div>
                    <ArrowRight className="w-3.5 h-3.5 text-gray-300 shrink-0" />
                    <div className="flex-1 relative">
                      <select
                        value={mapped ?? SKIP}
                        onChange={e => { setMappingEdited(true); setMapping(prev => ({ ...prev, [field.key]: e.target.value })); }}
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
                              onClick={() => { setMappingEdited(true); setMapping(prev => ({ ...prev, [field.key]: hint.column })); }}
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
                  </Fragment>
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
          </>)}
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
            {categoryText && <><span className="text-gray-300 text-xs">·</span><span className="text-xs text-gray-600">{categoryText}</span></>}
            {/* `periodFromTickets`: the booking dates, once the rows are read — nothing to miss before. */}
            {(periodText || !periodFromTickets) && <>
              <span className="text-gray-300 text-xs">·</span>
              <span className="text-xs text-gray-600">{periodText || <span className="text-red-400 italic">Dates missing</span>}</span>
            </>}
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
                <p className="text-xs text-gray-500">
                  {(serverImport ? summary?.rows ?? 0 : preview.total_rows).toLocaleString("en-IN")} rows parsed
                </p>
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
                disabled={!isStatementComplete || nothingNew || noVendorAtAll || tooLong > 0
                  || (duplicateCheck && !serverImport && dupBusy)}
                title={!isStatementComplete ? "Complete statement details first"
                  : noVendorAtAll ? "No row has a vendor yet — pick one for a supplier under Vendors in this file"
                  : tooLong > 0 ? `${tooLong.toLocaleString("en-IN")} row${tooLong === 1 ? " has" : "s have"} a value too long to save — fix or remove them under “Too long”`
                  : nothingNew ? dupShown?.reason ?? undefined : undefined}
                className="flex items-center gap-1.5 px-4 py-1.5 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {(duplicateCheck && !serverImport && dupBusy) || (serverImport && recounting)
                  ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  : <CheckCircle className="w-3.5 h-3.5" />}
                {duplicateCheck && !serverImport && dupBusy
                  ? <>Checking…</>
                  : duplicateCheck && dupShown && dupShown.duplicates > 0
                  ? <>Confirm & Save {dupShown.new.toLocaleString("en-IN")} New Row{dupShown.new === 1 ? "" : "s"}</>
                  : <>Confirm & Save {saveCount.toLocaleString("en-IN")} Row{saveCount === 1 ? "" : "s"}</>}
              </button>
            </div>
          </div>

          {duplicateCheck && (serverImport ? (
            <DuplicateBox check={dupShown} busy={false} error={null} onlyShown={gridView === "duplicates"}
              onToggleOnly={() => setGridView(v => (v === "duplicates" ? "all" : "duplicates"))}
              withVendor={allVendors} />
          ) : (
            <DuplicateBox check={dupCheck} busy={dupBusy} error={dupError} onlyShown={onlyRows != null}
              onToggleOnly={() => setOnlyDuplicates(v => !v)} withVendor={rowsWithoutVendor > 0} />
          ))}

          {/* `serverImport`: lines whose value is longer than its ticket field holds stop the save. */}
          {tooLong > 0 && summary && (
            <div className="flex items-start gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-800">
              <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
              <span>
                <strong>{tooLong.toLocaleString("en-IN")} row{tooLong === 1 ? " has" : "s have"} a value too long to save</strong>
                {" "}({summary.long_fields.map(f => `${colLabel(f.field)} over ${f.limit} characters: ${f.rows.toLocaleString("en-IN")}`).join("; ")}).
                {" "}Shorten them, or remove them, under{" "}
                <button type="button" onClick={() => setGridView("long")} className="font-semibold underline">Too long</button> — then save.
              </span>
            </div>
          )}

          {allVendors && (
            <VendorsPanel
              counts={supplierCounts} lines={supplierLines} picks={vendorPick} busy={suppliersBusy}
              agencies={agencyDirectory} unassigned={rowsWithoutVendor} total={totalRows}
              onPick={(group, value) => setVendorPick(prev => ({ ...prev, [group]: value }))}
              onShowRows={(name) => { if (serverImport) { setGridView("all"); setGridSearch(name); } else setFilterText(name); }}
            />
          )}

          {/* How the dates read in the declared format — change it here and the file is read
              again in it. */}
          {askDateFormats && datesShown.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 space-y-2">
              <p className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
                <CalendarDays className="w-4 h-4 text-gray-400" /> How your dates read
                {applyingMap && <RefreshCw className="w-3 h-3 animate-spin text-gray-400" />}
              </p>
              <DatesReadList dates={datesShown} formats={dates.formats} onChange={changeFormatOnPreview} />
              {dateFix && (
                <p className="text-[11px] text-sky-700">
                  {dateFix.count.toLocaleString("en-IN")} Excel date{dateFix.count === 1 ? "" : "s"} read
                  as {orderLabel(dates.formats.ticket_date)} — Excel had stored {dateFix.count === 1 ? "it" : "them"} with
                  day and month swapped ({dateFix.columns.map(c => `${c.column} ${c.cells}`).join(", ")}).
                </p>
              )}
              {datesShown.filter(d => d.unreadable > 0).map(d => (
                <p key={d.field} className="text-[11px] text-orange-700">
                  {d.unreadable.toLocaleString("en-IN")} {d.header} value{d.unreadable === 1 ? "" : "s"} can&apos;t be read
                  as {orderLabel(d.format)}: {d.cells.slice(0, 3).map(c => `"${c.value}" (row ${c.index + 1})`).join(", ")}
                  {d.unreadable > 3 ? ", …" : ""}. If they are all like that, pick another format; otherwise set them
                  in the grid{serverImport ? " (under “Dates not read”)" : ""} — they save empty.
                </p>
              ))}
            </div>
          )}

          {readWarnings.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-xs text-yellow-800 space-y-1">
              {readWarnings.map((w, i) => (
                <div key={i} className="flex items-center gap-2"><AlertCircle className="w-3.5 h-3.5 shrink-0" />{w}</div>
              ))}
            </div>
          )}

          {serverImport ? (importId && summary && (
            <ImportReviewGrid
              apiBase={apiBase} importId={importId} colGroups={reviewGroups} summary={summary}
              duplicateLabel={duplicateLabel} view={gridView} onView={setGridView}
              search={gridSearch} onSearch={setGridSearch} reloadKey={gridReload}
              onChanged={refreshJob} onError={showError}
            />
          )) : (<>
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
                  {reviewGroups.map(g=>(
                    <optgroup key={g.label} label={g.label}>
                      {g.cols.map(c=><option key={c.key} value={c.key}>{c.label}</option>)}
                    </optgroup>
                  ))}
                </select>
                {bulkColKey&&(()=>{
                  const colType=COL_TYPE[bulkColKey]??"text";
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
              colGroups={reviewGroups}
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
          </>)}
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
