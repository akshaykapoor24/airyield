"use client";

// Upload a vendor statement through map → review & edit → confirm. Used by the
// third-party (consolidator) types and by NDC; `requireSupplier` is the only difference
// between them on screen.
//
// WHY A WIZARD AND NOT THE ONE-SHOT MODAL. These types have no single fixed export. A
// consolidator writes whatever spreadsheet it likes, and every airline runs its own NDC
// portal with its own header names. The alias map covers the shapes we have seen —
// including our own Template, which comes back fully mapped and needs no work — but the
// next file will have its own headers, and the old modal's only answer to that was "8 of
// your 40 columns were recognised" after the rows were already saved. Here the mapping is
// a step the user can see and fix before anything is written.
//
// THE STEPS ARE SHOWN EVEN WHEN NOTHING NEEDS DOING. A file that matches the Template
// lands on Map columns fully filled in and the user presses Next twice. That is
// deliberate: the same four steps every time is easier to learn than a screen that
// sometimes appears, and the review pass is worth having on a file nobody has checked.
//
// THE STATEMENT PERIOD (Third Party GDS — `captures_period` from /standard-columns, so the
// Payment Module's route gets it too). The upload step asks which days the statement covers,
// pre-filled from the file name when it says ("…01-07TH AUG 26.xlsx"), and before the file is
// read says when that period — or part of it — is already uploaded for the agency.
//
// DUPLICATES (Third Party GDS — backend services/tp_gds_reupload.py). Every entry is checked
// against every statement already saved for the agency, whatever its period, and against the
// rest of the file. The review step puts each in a bucket — Already uploaded (left out unless
// saved again), Partial duplicate (same ticket, something changed: saved and flagged unless
// left out), Repeated in this file (saved and flagged unless left out), New — and the user
// chooses per bucket and row by row. Save sums it all up once more before anything is written.
// The review step also flags every ticket whose Booked Date or Issue Date falls outside the
// period — a refund of an older ticket, a late posting, or the wrong period. They are
// flagged, not dropped: the user decides. The period
// and the date formats are sent with /extract too: rows typed in the sheet's format into an
// Excel set the other way round ("01-08-2026" stored as 8 Jan) have their Excel dates put back
// in that format, row by row against the period (backend services/excel_dates.py), and the
// cells read that way are blue on the review step.
//
// THE DATE FORMAT (Third Party GDS — `date_formats` from /standard-columns). "05/08/2026" is
// 5 Aug in one consolidator's sheet and 8 May in the next, and only the uploader knows which,
// so the upload step asks how Booked Date and Date of Travel are written — filled in from the
// file itself where it shows it (backend services/date_format_detect.py: "13/08/2026" can only
// be day-first, and a week of Booked Dates lands in the statement period only one way round),
// else from the agency's last upload. The file's text dates are read in that order and no other (backend
// flat_statement.to_iso_date); a cell that cannot be is not read the other way round but left
// out and shown. The review step says how each column read — how many dates, from when to
// when, and which cells did not fit — and the format can be changed right there.
//
// TWO LAYOUTS. A popup over the uploads list (email intake, the Payment Module, most types)
// or, with `layout="page"`, a page of its own under the Statements tabs (Third Party GDS —
// lib/statements.ts `uploadPage`), with room for the mapping and review grids. Same steps.
//
// Modelled on components/statements/lcc/LccUploadWizard.tsx, which does the same job for
// LCC Detailed. The two are not shared because that one ingests asynchronously behind a
// progress poller and has no per-cell editing — the mapping screens look alike, the rest
// of the flow does not.

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  X, Upload, FileSpreadsheet, CheckCircle2, Loader2, Search, AlertTriangle,
  ArrowLeft, ArrowRight, Wand2, Eraser, PartyPopper, Pencil, RotateCcw, Filter,
  Sparkles, CalendarRange, CalendarCheck, ClipboardCheck,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import { notifyRequired } from "@/lib/requiredFields";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import StatementAgencyField, { agencyBlockReason, channelForApiBase } from "@/components/statements/StatementAgencyField";
import { type VendorAgency, loadVendorAgencies } from "@/lib/vendorAgency";
import { formatDay, formatPeriod, formatUploadedAt } from "@/lib/statementPeriod";
import {
  type DateField, type DateFormats, type DateOrder, type DatesRead, type DetectedFormat,
  DateFormatSection, DatesReadList, orderLabel, useDateFormats,
} from "@/components/statements/dateFormat";

type Step = "upload" | "mapping" | "review" | "done";

type StdCol = { header: string; field: string; group: string };
type StdGroup = { group: string; columns: StdCol[] };
type FieldGroup = { label: string; fields: string[]; headers: string; consequence?: string };
/** Rows this type discards on content rather than importing — NDC's unpaid holds and free
 *  seats, and nothing else so far. Null for every other type. The API enforces it at
 *  confirm; this is only what lets the review step show which rows are about to go. */
type RowFilter = {
  field: string;        // the mapped field the rule reads, e.g. "txn_type"
  header: string;       // its canonical header, for prose
  exclude: string[];    // normalised values that are dropped
  keep: string[];       // the ones that survive, listed for the user
  label: string;        // "unpaid and free-seat rows"
  note: string;
};
type StdResp = {
  groups: StdGroup[]; required: FieldGroup[]; advisory: FieldGroup[]; total: number;
  row_filter: RowFilter | null;
  /** Third Party GDS: the upload declares its statement period, is asked about first when
   *  that period is already uploaded, and the review step asks `/save-preview` what Save
   *  would leave out as already saved. */
  captures_period?: boolean;
  /** Third Party GDS: the date columns whose written order the upload declares. */
  date_formats?: DateField[];
};

type SampleRow = Record<string, string | null> & { __index__: number };
type ExtractResp = {
  file_name: string;
  file_digest: string;
  header_row: number;
  total_rows: number;
  preview_rows: number;
  preview_limit: number;
  columns: string[];
  suggested_mapping: Record<string, string>;   // {field: source column}
  matched_columns: number;
  standard_total: number;
  is_template_match: boolean;
  sample_rows: SampleRow[];
  supplier_name: string | null;
  /** Null for every type but Third Party API, whose one table holds several vendor shapes
   *  (MakeMyTrip, TBO). Shown as reassurance on the mapping step and deliberately not
   *  editable: for a spec-driven type the mapping IS the parser, and the user is looking
   *  straight at it. `detects_format` true with a null format means "not recognised" —
   *  which still imports, just without a vendor label. */
  source_format?: string | null;
  source_format_label?: string | null;
  detects_format?: boolean;
  /** Which free-text field an AI pass may read, and the only fields it may fill. */
  ai_narration?: AiNarrationCfg | null;
  /** Third Party GDS: Excel dates stored with day and month swapped ("01-08-2026" typed
   *  day-first, kept as 8 Jan), put back in the declared format. Null when none. */
  date_fix?: DateFixInfo | null;
};

type DateFixInfo = {
  period_label: string;
  count: number;
  columns: { column: string; cells: number }[];
  /** The changed cells of the rows shown — `column` is the file's own header. */
  cells: { index: number; column: string; stored: string; read: string }[];
};

type AiNarrationCfg = { source_field: string; fields: string[]; label: string };

type AiParseResp = {
  /** The union of fields actually filled — what the review grid must reveal. */
  fields: string[];
  /** {rowIndex: {field: value}}, keyed by the same `__index__` we sent. */
  rows: Record<string, Record<string, string>>;
  requested_rows: number;
  parsed_rows: number;
  confidence: number;
  warning: string | null;
};

type SaveResp = {
  inserted: number;
  edited_rows: number;
  /** Rows dropped by `row_filter` — 0 for the types that drop nothing. */
  excluded_rows: number;
  /** Null unless the type has a row filter; false means its column was never mapped, so
   *  nothing was classified and nothing was skipped. */
  filter_column_mapped: boolean | null;
  /** The statement's own OLD/BALANCE/payment lines among `inserted`. */
  balance_rows?: number;
  /** Control figures, for the types that capture them (`captureControls`). */
  controls?: {
    file_rows: number | null;
    loaded_rows: number | null;
    ticket_rows: number;
    ticket_net: string | null;
    expected_count: number | null;
    expected_amount: string | null;
    opening_balance: string | null;
    closing_balance: string | null;
    /** Entries of the file left out as already uploaded — still part of what it declares. */
    duplicate_rows?: number;
    duplicate_net?: string | null;
  } | null;
  /** The statement period saved with the upload (Third Party GDS), YYYY-MM-DD. */
  period_from?: string | null;
  period_to?: string | null;
  /** Third Party GDS: each bucket of duplicates — found, saved, left out. */
  duplicates?: DuplicateReport | null;
  /** Third Party GDS: saved tickets dated outside the period, as reviewed. */
  outside_period?: number | null;
  /** Third Party GDS: the date formats the dates were read in, as saved with the upload. */
  date_formats?: DateFormats | null;
};

/** An earlier upload of this agency — one whose period overlaps the one entered (asked about
 *  before reading), or one holding a line this file repeats. */
type EarlierUpload = {
  batch_id: string;
  source_file: string | null;
  period_from: string | null;
  period_to: string | null;
  period_label: string;
  uploaded_at: string | null;
  total_entries: number;
  new_entries: number;
  /** Lines of THIS file it already holds — on the review preview and the save result. */
  matched?: number;
  exact?: number;
  partial?: number;
};

/** Which kind of duplicate a line of the file is (backend services/tp_gds_reupload.py). */
type DupKind = "exact" | "partial" | "in_file";
type DupChoice = "save" | "skip";
type DupChoices = Record<DupKind, DupChoice>;
const DUP_KINDS: DupKind[] = ["exact", "partial", "in_file"];
/** What Save does with each bucket unless told otherwise — backend DEFAULT_CHOICES. */
const DEFAULT_DUP_CHOICES: DupChoices = { exact: "skip", partial: "save", in_file: "save" };

/** A field on which a line differs from the one it repeats. `field` "passenger" is the
 *  printed name, else First + Last. */
type DupField = { field: string; label: string; file: string | null; saved: string | null };

/** A duplicate row of the file: what kind, the saved line's upload (exact / partial), the
 *  file row it repeats (in_file), and what differs. */
type DupMark = {
  index: number | null;
  kind: DupKind;
  batch_id: string | null;
  of_index: number | null;
  fields: DupField[];
};

/** …with what the line holds and where its twin is saved, for the lists. */
type DupLine = DupMark & {
  ticket_number: string | null;
  passenger_name: string | null;
  ticket_status: string | null;
  booking_date: string | null;
  issue_date: string | null;
  net_amount: string | null;
  source_file: string | null;
  period_label: string | null;
};

type BucketCounts = Record<DupKind | "new", number>;

/** The done screen: what Save did with each bucket. */
type DuplicateReport = {
  period_label: string;
  earlier: EarlierUpload[];
  total: number;                       // entries in the file (balance lines not counted)
  counts: BucketCounts;
  saved: Record<DupKind, number>;
  left_out: Record<DupKind, number>;
  left_out_total: number;
  left_out_net: string;
  new: number;                         // entries saved, duplicates saved by choice included
  left_out_lines: DupLine[];           // the first 200
};

/** `/save-preview`: what is in the file as mapped and edited, against every statement already
 *  saved for the agency — nothing written. The choices are applied here, on `rows`. */
type SavePreview = {
  period_label: string;
  earlier: EarlierUpload[];
  total: number;
  balance_lines: number;
  counts: BucketCounts;
  defaults: DupChoices;
  /** Every duplicate row of the file. */
  rows: DupMark[];
  /** The first 200 of them, with what they hold. */
  listed: DupLine[];
  net: Record<DupKind | "new", string>;
  /** The file's own Week values that fall outside the entered period. */
  week_outside: { week: string; period_label: string; rows: number }[];
  /** Tickets whose Booked Date or Issue Date is not in the period — flagged, still saved. */
  outside_period: OutsidePeriod;
  /** How each declared date column read in its format. */
  dates?: DatesRead[];
  /** File rows that are the statement's own OLD / BALANCE lines. */
  balance_rows?: number[];
  /** File rows holding a value that could not be read into its field, and which fields. */
  unparsed_rows?: { index: number; fields: string[] }[];
};

/** Where a ticket's date sits against the statement period. */
type OutsideSide = "before" | "after" | "unreadable";
type PeriodDateField = "booking_date" | "issue_date";
type OutsideDates = Partial<Record<PeriodDateField, OutsideSide>>;

type OutsideLine = {
  ticket_number: string | null;
  passenger_name: string | null;
  ticket_status: string | null;
  booking_date: string | null;
  issue_date: string | null;
  net_amount: string | null;
  index: number | null;
  outside: OutsideDates;
};

type OutsidePeriod = {
  period_label: string;
  count: number;
  lines: OutsideLine[];                               // the first 200
  rows: { index: number; outside: OutsideDates }[];   // every one, for the grid
};

const SIDE_TEXT: Record<OutsideSide, string> = {
  before: "before the period", after: "after the period", unreadable: "not a readable date",
};
const DATE_LABEL: Record<PeriodDateField, string> = { booking_date: "Booked Date", issue_date: "Issue Date" };

const fmtAmt = (v: string | number | null | undefined) =>
  v == null || v === "" ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

const SKIP = "";        // "— not in file —"
const PAGE = 25;

/** Must match ndc_spec._norm_txn — "Paid Booking" and "paid-booking" are PAID_BOOKING.
 *  The API is what actually decides; this only has to agree with it well enough that the
 *  preview greys the same rows the import drops. */
const normTxn = (v: string) => v.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "");

function errMsg(e: unknown, fallback: string): string {
  const m = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return typeof m === "string" ? m : fallback;
}

/** `inline`: no band of its own — sits in the page layout's title bar. */
function StepBar({ step, inline = false }: { step: Step; inline?: boolean }) {
  const steps: { key: Step; label: string }[] = [
    { key: "upload", label: "Upload" },
    { key: "mapping", label: "Map columns" },
    { key: "review", label: "Review & edit" },
    { key: "done", label: "Save" },
  ];
  const order: Step[] = ["upload", "mapping", "review", "done"];
  const activeIdx = order.indexOf(step);
  return (
    <div className={`flex flex-wrap items-center gap-2 ${
      inline ? "" : "px-5 py-3 border-b border-slate-100 bg-slate-50/60"}`}>
      {steps.map((s, i) => {
        const done = order.indexOf(s.key) < activeIdx;
        const active = s.key === step;
        return (
          <div key={s.key} className="flex items-center gap-2">
            <div className={`flex items-center gap-1.5 text-[11px] font-semibold ${active ? "text-blue-600" : done ? "text-emerald-600" : "text-slate-400"}`}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${active ? "bg-blue-600 text-white" : done ? "bg-emerald-500 text-white" : "bg-slate-200 text-slate-500"}`}>
                {done ? "✓" : i + 1}
              </span>
              {s.label}
            </div>
            {i < steps.length - 1 && <div className="w-6 h-px bg-slate-200" />}
          </div>
        );
      })}
    </div>
  );
}

/** The done screen's completeness lines: tickets vs balance lines, and what was declared. */
function ControlsSummary({ controls, balanceRows }: {
  controls: NonNullable<SaveResp["controls"]>; balanceRows: number;
}) {
  const lines: { ok: boolean | null; text: string }[] = [];
  lines.push({
    ok: null,
    text: `${controls.ticket_rows} ticket${controls.ticket_rows === 1 ? "" : "s"}`
      + (balanceRows ? ` + ${balanceRows} balance line${balanceRows === 1 ? "" : "s"}` : "")
      + ` · net ${fmtAmt(controls.ticket_net)}`,
  });
  if (controls.opening_balance != null || controls.closing_balance != null) {
    lines.push({ ok: null, text: `Opening ${fmtAmt(controls.opening_balance)} · closing ${fmtAmt(controls.closing_balance)}` });
  }
  // The declared totals cover the whole file, entries already uploaded included.
  const dupRows = controls.duplicate_rows ?? 0;
  const dupNet = Number(controls.duplicate_net ?? 0);
  if (controls.expected_count != null) {
    lines.push({
      ok: controls.expected_count === controls.ticket_rows + dupRows,
      text: `Expected ${controls.expected_count} records, loaded ${controls.ticket_rows}`
        + (dupRows ? ` (+${dupRows} already uploaded)` : ""),
    });
  }
  if (controls.expected_amount != null) {
    const diff = Math.abs(Number(controls.expected_amount) - Number(controls.ticket_net ?? 0) - dupNet);
    lines.push({
      ok: diff <= 1,
      text: `Expected ${fmtAmt(controls.expected_amount)}, loaded ${fmtAmt(controls.ticket_net)}`
        + (dupRows ? ` (+${fmtAmt(dupNet)} already uploaded)` : ""),
    });
  }
  return (
    <div className="mt-2 space-y-0.5">
      {lines.map((l, i) => (
        <p key={i} className={`text-xs ${l.ok === null ? "text-slate-600" : l.ok ? "text-emerald-600" : "text-amber-600"}`}>
          {l.ok === null ? "" : l.ok ? "✓ " : "≠ "}{l.text}
        </p>
      ))}
    </div>
  );
}

/** "test1.xlsx (01–07 Aug 2026, uploaded 16/10/2026, 7:29:32 pm)" — an earlier upload, named. */
function earlierName(e: EarlierUpload): string {
  return `${e.source_file ?? "an earlier upload"} (${e.period_label}, uploaded ${formatUploadedAt(e.uploaded_at)})`;
}

const DUP_LABEL: Record<DupKind, string> = {
  exact: "Already uploaded", partial: "Partial duplicate", in_file: "Repeated in this file",
};

/** A compared value as a person reads it: an amount in rupees, a date as a day. */
function fmtDupValue(f: DupField, v: string | null): string {
  if (v == null || v === "") return "(blank)";
  if (f.field === "base_fare" || f.field === "net_amount") return fmtAmt(v);
  if (f.field === "booking_date" || f.field === "issue_date") return formatDay(v);
  return v;
}

/** "Net Amount ₹1,101 → ₹1,250" — what this line changed against the one it repeats. */
function changesText(fields: DupField[]): string {
  return fields.map((f) => `${f.label} ${fmtDupValue(f, f.saved)} → ${fmtDupValue(f, f.file)}`).join(" · ");
}

/** Where a duplicate's twin is: the earlier statement holding it, or the file's own row. */
function twinText(m: DupMark, upload?: EarlierUpload | null): string {
  if (m.kind === "in_file") return m.of_index != null ? `row ${m.of_index + 1} of this file` : "an earlier row of this file";
  return upload ? earlierName(upload) : "an earlier upload";
}

/** The lines of the file a save left out, and why. */
function LeftOutTable({ rows }: { rows: DupLine[] }) {
  return (
    <div className="mt-1.5 max-h-48 overflow-y-auto border border-slate-200 rounded-md bg-white">
      <table className="w-full text-[11px] text-left">
        <thead className="bg-slate-50 text-slate-500 sticky top-0">
          <tr>
            <th className="px-2 py-1 font-medium">Row</th>
            <th className="px-2 py-1 font-medium">Ticket</th>
            <th className="px-2 py-1 font-medium">Passenger</th>
            <th className="px-2 py-1 font-medium">Status</th>
            <th className="px-2 py-1 font-medium text-right">Net</th>
            <th className="px-2 py-1 font-medium">Left out as</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-slate-100 text-slate-700">
              <td className="px-2 py-1 text-slate-400 tabular-nums">{r.index != null ? r.index + 1 : "—"}</td>
              <td className="px-2 py-1 font-mono">{r.ticket_number ?? "—"}</td>
              <td className="px-2 py-1">{r.passenger_name ?? "—"}</td>
              <td className="px-2 py-1">{r.ticket_status ?? "—"}</td>
              <td className="px-2 py-1 text-right">{fmtAmt(r.net_amount)}</td>
              <td className="px-2 py-1 text-slate-500">
                {DUP_LABEL[r.kind]} ·{" "}
                {r.kind === "in_file"
                  ? twinText(r)
                  : `${r.period_label ?? "—"} · ${r.source_file ?? "an earlier upload"}`}
                {r.fields.length > 0 && <span className="block text-slate-400">{changesText(r.fields)}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The done screen: what the save did with each bucket of duplicates. */
function DuplicatesSummary({ report }: { report: DuplicateReport }) {
  const [show, setShow] = useState(false);
  const found = DUP_KINDS.filter((k) => report.counts[k] > 0);
  const where = report.earlier.filter((e) => e.matched).map((e) => e.source_file ?? "an earlier upload");
  const n = (v: number) => v.toLocaleString("en-IN");
  return (
    <div className="mt-3 w-full max-w-2xl text-left">
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 space-y-1">
        {found.length === 0 ? (
          <p className="text-xs text-slate-700">
            Checked against this agency&apos;s saved statements — none of these entries was saved before.
          </p>
        ) : (
          <>
            {found.map((k) => (
              <p key={k} className="text-xs text-slate-700">
                <strong>{n(report.counts[k])} {DUP_LABEL[k].toLowerCase()}</strong>
                {k !== "in_file" && where.length > 0 && <> (in {where.join(", ")})</>}
                {" — "}
                {report.saved[k] > 0 && <>{n(report.saved[k])} saved, flagged</>}
                {report.saved[k] > 0 && report.left_out[k] > 0 && " · "}
                {report.left_out[k] > 0 && <>{n(report.left_out[k])} not saved</>}.
              </p>
            ))}
            {report.left_out_total > 0 && (
              <p className="text-xs text-slate-500">
                Left out: {n(report.left_out_total)} {report.left_out_total === 1 ? "entry" : "entries"} ·
                net {fmtAmt(report.left_out_net)}.{" "}
                <button onClick={() => setShow((v) => !v)} className="text-blue-600 hover:underline">
                  {show ? "Hide" : "Show"} them
                </button>
              </p>
            )}
          </>
        )}
        {show && <LeftOutTable rows={report.left_out_lines} />}
        {show && report.left_out_lines.length < report.left_out_total && (
          <p className="text-[11px] text-slate-500 mt-1">Showing the first {report.left_out_lines.length}.</p>
        )}
      </div>
    </div>
  );
}

/** Said on the mapping step when Excel-stored dates were put back in the sheet's order. */
function DateFixNote({ fix, format }: { fix: DateFixInfo; format: string }) {
  const ex = fix.cells[0];
  return (
    <div className="flex items-start gap-2 px-3 py-2 mb-3 rounded-xl border border-sky-200 bg-sky-50 text-xs text-sky-800"
      title={`These rows were typed as ${format} into an Excel set the other way round, so Excel stored the day as the month. Each row's Booked Date against ${fix.period_label} shows which rows: rows pasted in correctly, and dates kept as text, are unchanged.`}>
      <CalendarCheck className="w-4 h-4 shrink-0 mt-px text-sky-500" />
      <span>
        <strong>
          {fix.count.toLocaleString("en-IN")} Excel date{fix.count === 1 ? "" : "s"} read as {format}
        </strong>{" "}
        — Excel had stored {fix.count === 1 ? "it" : "them"} with day and month swapped
        {ex && <> (e.g. {formatDay(ex.stored)} → {formatDay(ex.read)})</>}:{" "}
        {fix.columns.map((c) => `${c.column} ${c.cells.toLocaleString("en-IN")}`).join(", ")}.
        Blue in the review grid.
      </span>
    </div>
  );
}

/** What the review grid can be narrowed to — one per count on the Statement check. */
type GridFilter = "all" | DupKind | "new" | "before" | "after" | "unparsed" | "edited";

const FILTER_LABEL: Record<GridFilter, string> = {
  all: "All entries", exact: "Already uploaded", partial: "Partial dup.", in_file: "Repeated in file",
  new: "New", before: "Before period", after: "After period", unparsed: "Not read", edited: "Edited",
};

const TILE_TONE = {
  slate:   { text: "text-slate-800",   on: "border-slate-400 bg-slate-50 ring-1 ring-slate-300" },
  emerald: { text: "text-emerald-700", on: "border-emerald-300 bg-emerald-50 ring-1 ring-emerald-300" },
  rose:    { text: "text-rose-700",    on: "border-rose-300 bg-rose-50 ring-1 ring-rose-300" },
  orange:  { text: "text-orange-700",  on: "border-orange-300 bg-orange-50 ring-1 ring-orange-300" },
  amber:   { text: "text-amber-700",   on: "border-amber-300 bg-amber-50 ring-1 ring-amber-300" },
  fuchsia: { text: "text-fuchsia-700", on: "border-fuchsia-300 bg-fuchsia-50 ring-1 ring-fuchsia-300" },
  indigo:  { text: "text-indigo-700",  on: "border-indigo-300 bg-indigo-50 ring-1 ring-indigo-300" },
} as const;

/** Each kind of duplicate's colours — its tile, its tag in the grid, its changed cells. */
const DUP_TONE: Record<DupKind, { tile: keyof typeof TILE_TONE; tag: string; cell: string }> = {
  exact:   { tile: "amber",   tag: "bg-amber-100 text-amber-800",     cell: "" },
  partial: { tile: "fuchsia", tag: "bg-fuchsia-100 text-fuchsia-800", cell: "border-dashed border-fuchsia-400 bg-fuchsia-50 text-fuchsia-900 font-medium" },
  in_file: { tile: "indigo",  tag: "bg-indigo-100 text-indigo-800",   cell: "border-dashed border-indigo-400 bg-indigo-50 text-indigo-900 font-medium" },
};

/** The grid columns a compared field is shown in. */
const DIFF_COLUMNS: Record<string, string[]> = {
  passenger: ["passenger_name", "first_name", "last_name"],
};

/** One count on the Statement check, and the filter it puts on the grid below. */
function Tile({ label, hint, value, tone, active, onClick, title }: {
  label: string; hint: string; value: number | null; tone: keyof typeof TILE_TONE;
  active: boolean; onClick: () => void; title: string;
}) {
  const none = value === 0;
  return (
    <button type="button" onClick={onClick} disabled={none && !active} aria-pressed={active} title={title}
      className={`min-w-0 text-left rounded-lg border px-3 py-2 transition-colors ${
        active ? TILE_TONE[tone].on
          : none ? "border-slate-200 bg-white cursor-default"
          : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}`}>
      <span className="block text-[10px] font-semibold uppercase tracking-wide text-slate-500 truncate">{label}</span>
      <span className={`block text-lg font-bold leading-tight tabular-nums ${
        none || value == null ? "text-slate-300" : TILE_TONE[tone].text}`}>
        {value == null ? "—" : value.toLocaleString("en-IN")}
      </span>
      <span className="block text-[10px] text-slate-400 truncate">{hint}</span>
    </button>
  );
}

/** A line under the counts: what Save will do, and what needs a look. */
type CheckNote = { tone: "ok" | "info" | "fix" | "warn" | "bad"; text: ReactNode };
const NOTE_STYLE: Record<CheckNote["tone"], { cls: string; Icon: typeof CheckCircle2 }> = {
  ok:   { cls: "text-emerald-700", Icon: CheckCircle2 },
  info: { cls: "text-slate-600",   Icon: CalendarRange },
  fix:  { cls: "text-sky-700",     Icon: CalendarCheck },
  warn: { cls: "text-amber-700",   Icon: AlertTriangle },
  bad:  { cls: "text-red-700",     Icon: AlertTriangle },
};

/** The review step's one box (Third Party GDS): what this statement holds and what Save will
 *  do with it — each count a filter on the grid below — what to do with each bucket of
 *  duplicates (`children`), how its dates read, in which format (changeable here; the check
 *  runs again), and the few things that need a look. */
function ReviewSummary({ counts, hints, balanceLines, filter, onFilter, periodLabel, busy, dates, formats,
  onFormat, notes, children }: {
  counts: Record<GridFilter, number | null>;
  /** What Save does with each bucket of duplicates, as chosen — the tile's second line. */
  hints: Record<DupKind, string>;
  balanceLines: number;
  filter: GridFilter;
  onFilter: (f: GridFilter) => void;
  periodLabel: string;
  busy: boolean;
  dates: DatesRead[];
  formats: DateFormats;
  onFormat: (field: string, o: DateOrder) => void;
  notes: CheckNote[];
  children?: ReactNode;
}) {
  const tiles: { key: GridFilter; hint: string; tone: keyof typeof TILE_TONE; title: string }[] = [
    { key: "all", tone: "slate",
      hint: balanceLines ? `+ ${balanceLines} balance line${balanceLines === 1 ? "" : "s"}` : "in this statement",
      title: "Every ticket line in the file. The statement's own OLD / BALANCE lines are not entries." },
    { key: "exact", tone: DUP_TONE.exact.tile, hint: hints.exact,
      title: "Exactly the same as a line already saved for this agency, in any earlier statement — same ticket, status, passenger, booked date, issue date, basic fare and net amount. Not saved again unless you choose to." },
    { key: "partial", tone: DUP_TONE.partial.tile, hint: hints.partial,
      title: "The same ticket and status as a line already saved for this agency, but the passenger, a date or an amount changed. Saved and flagged unless you leave it out; the changed cells are outlined." },
    { key: "in_file", tone: DUP_TONE.in_file.tile, hint: hints.in_file,
      title: "The same ticket and status as an earlier row of this very file. Saved and flagged unless you leave it out." },
    { key: "new", tone: "emerald", hint: "will be saved",
      title: "Lines no statement of this agency holds yet." },
    { key: "before", tone: "rose", hint: "Booked / Issue Date",
      title: `Tickets whose Booked Date or Issue Date is before ${periodLabel} — often a refund or reissue of an older ticket. Saved with this statement; check them.` },
    { key: "after", tone: "rose", hint: "Booked / Issue Date",
      title: `Tickets whose Booked Date or Issue Date is after ${periodLabel} — often a late posting, or the wrong period. Saved with this statement; check them.` },
    { key: "unparsed", tone: "orange", hint: "a value didn't fit its field",
      title: "Rows with a date that doesn't fit its column's format, or text where an amount belongs. That value is saved empty unless you correct it." },
    { key: "edited", tone: "slate", hint: "rows you corrected",
      title: "Rows you changed on this step." },
  ];
  return (
    <div className="mb-3 rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-slate-100">
        <p className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
          <ClipboardCheck className="w-4 h-4 text-slate-400" />
          Statement check
          {periodLabel && <span className="font-normal text-slate-400">· {periodLabel}</span>}
          {busy && <Loader2 className="w-3 h-3 animate-spin text-slate-400" />}
        </p>
        {filter !== "all" && (
          <button onClick={() => onFilter("all")} className="text-[11px] font-medium text-blue-600 hover:underline">
            Show all rows
          </button>
        )}
      </div>
      <div className="p-3 space-y-3">
        <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 2xl:grid-cols-9">
          {tiles.map((t) => (
            <Tile key={t.key} label={FILTER_LABEL[t.key]} hint={t.hint} tone={t.tone} title={t.title}
              value={counts[t.key]} active={filter === t.key}
              onClick={() => onFilter(filter === t.key ? "all" : t.key)} />
          ))}
        </div>
        {children}
        {dates.length > 0 && <DatesReadList dates={dates} formats={formats} onChange={onFormat} />}
        {notes.length > 0 && (
          <ul className="space-y-1 text-xs">
            {notes.map((n, i) => {
              const { cls, Icon } = NOTE_STYLE[n.tone];
              return (
                <li key={i} className={`flex items-start gap-1.5 ${cls}`}>
                  <Icon className="w-3.5 h-3.5 shrink-0 mt-px" />
                  <span>{n.text}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

const CHOICE_TEXT: Record<DupKind, { save: string; skip: string; what: string }> = {
  exact:   { save: "Save again",    skip: "Don't save", what: "already saved" },
  partial: { save: "Save, flagged", skip: "Don't save", what: "same ticket & status as a saved line, something changed" },
  in_file: { save: "Save, flagged", skip: "Don't save", what: "the same ticket & status as an earlier row of this file" },
};

/** One line per bucket of duplicates in the file: how many, where they are saved, and what
 *  Save does with the bucket — the grid's ticks change single rows. */
function DuplicateChoices({ counts, net, choices, onChoose, overridden, onReset, earlier }: {
  counts: BucketCounts;
  net: Record<DupKind | "new", string>;
  choices: DupChoices;
  onChoose: (k: DupKind, c: DupChoice) => void;
  /** Rows of each bucket ticked on the grid the other way from the bucket. */
  overridden: Record<DupKind, number>;
  onReset: (k: DupKind) => void;
  earlier: EarlierUpload[];
}) {
  const shown = DUP_KINDS.filter((k) => counts[k] > 0);
  if (!shown.length) return null;
  const where = earlier.filter((e) => e.exact).map((e) => `${e.period_label} (${e.source_file ?? "an earlier upload"})`);
  return (
    <div className="rounded-lg border border-slate-200 divide-y divide-slate-100">
      {shown.map((k) => {
        const n = counts[k];
        // The default first, so the recommended answer is always on the left.
        const order: DupChoice[] = DEFAULT_DUP_CHOICES[k] === "skip" ? ["skip", "save"] : ["save", "skip"];
        return (
          <div key={k} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2 text-xs">
            <span className={`shrink-0 rounded px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide ${DUP_TONE[k].tag}`}>
              {DUP_LABEL[k]}
            </span>
            <span className="min-w-0 flex-1 text-slate-700">
              <strong>{n.toLocaleString("en-IN")}</strong> {n === 1 ? "entry" : "entries"} — {CHOICE_TEXT[k].what}
              {k === "exact" && where.length > 0 && (
                <> in {where.slice(0, 2).join(", ")}{where.length > 2 ? ` and ${where.length - 2} more` : ""}</>
              )}
              <span className="text-slate-400"> · net {fmtAmt(net[k])}</span>
              {overridden[k] > 0 && (
                <span className="text-slate-500">
                  {" "}· {overridden[k]} row{overridden[k] === 1 ? "" : "s"} set on the grid{" "}
                  <button onClick={() => onReset(k)} className="text-blue-600 hover:underline">reset</button>
                </span>
              )}
            </span>
            <div className="inline-flex shrink-0 rounded-lg border border-slate-200 bg-slate-50 p-0.5" role="radiogroup"
              aria-label={`What to do with ${DUP_LABEL[k].toLowerCase()} entries`}>
              {order.map((c) => {
                const on = choices[k] === c;
                return (
                  <button key={c} type="button" role="radio" aria-checked={on} onClick={() => onChoose(k, c)}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-colors ${
                      on ? `bg-white shadow-sm ${c === "save" ? "text-emerald-700" : "text-slate-800"}`
                        : "text-slate-400 hover:text-slate-600"}`}>
                    {CHOICE_TEXT[k][c]}
                    {c === DEFAULT_DUP_CHOICES[k] && <span className="ml-1 font-normal text-slate-400">(default)</span>}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function StatementUploadWizard({
  apiBase, title, requireSupplier = false, captureControls = false, doneHint, onClose, onDone,
  initialFile = null, initialAgencyId = null, initialControls, initialPeriod,
  layout = "modal", backLabel,
}: {
  apiBase: string;
  title: string;
  /** "modal": a popup over the caller. "page": a page of its own — the caller's route renders
   *  it, `onClose` / `onDone` navigate back, and leaving mid-mapping asks first. */
  layout?: "modal" | "page";
  /** Page layout: the back link's text, e.g. "GDS uploads". */
  backLabel?: string;
  /** Third-party types only — the uploader must name the consolidator from their own Agency
   *  Master, because the file never says who sent it and the B2B deal is matched
   *  against the answer. Off for NDC: an airline's own export names its carrier, so there is
   *  nothing for the uploader to declare and asking would be a question with no purpose. */
  requireSupplier?: boolean;
  /** Payment Module only — ask for the statement's expected record count and net amount
   *  (the vendor's covering note), so the import can be checked against them. Mirrors
   *  `captures_controls` in the backend spec, which is what stores them. */
  captureControls?: boolean;
  /** One line on the success screen telling the user where the rows went. */
  doneHint?: string;
  onClose: () => void;
  onDone: () => void;
  /** Email intake → Process: the attachment to start from. Skips the drop zone and goes
   *  straight to mapping once the consolidator (below) is known. */
  initialFile?: File | null;
  /** The sender's Agency Master row — the consolidator the email came from. */
  initialAgencyId?: number | null;
  /** Control totals read from the email's covering note ("245 tickets, net ₹12,34,567"). */
  initialControls?: { count?: number | null; amount?: string | null };
  /** The statement period read from the email (subject, covering note, attachment names),
   *  YYYY-MM-DD. Used only when the attachment's own name gives none. */
  initialPeriod?: { from?: string | null; to?: string | null };
}) {
  const [step, setStep] = useState<Step>("upload");
  const [std, setStd] = useState<StdResp | null>(null);
  const [extracted, setExtracted] = useState<ExtractResp | null>(null);
  const [columnMap, setColumnMap] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<SaveResp | null>(null);

  // Upload
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [agency, setAgency] = useState<VendorAgency | null>(null);
  // The supplier-master row the agency was copied from — what the upload is attributed to.
  // See StatementAgencyField.
  const supplierId = requireSupplier ? agency?.supplier_id ?? null : null;
  const inputRef = useRef<HTMLInputElement>(null);
  // Optional control totals (captureControls). Kept as typed; parsed once on save.
  const [expectedCount, setExpectedCount] = useState("");
  const [expectedAmount, setExpectedAmount] = useState("");

  // The statement period (Third Party GDS — `captures_period`), YYYY-MM-DD. Read off the file
  // name when it says, typed otherwise. `periodGuessed`: the dates came from a name or the
  // email, so picking another file may replace them — dates the user typed are never replaced.
  const capturesPeriod = !!std?.captures_period;
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [periodNote, setPeriodNote] = useState<{ tone: "ok" | "ask"; text: string } | null>(null);
  const [periodGuessed, setPeriodGuessed] = useState(false);
  const periodSeq = useRef(0);
  // The agency's uploads whose period overlaps the one entered — asked about before reading.
  const [earlier, setEarlier] = useState<EarlierUpload[] | null>(null);
  const [checkingPeriod, setCheckingPeriod] = useState(false);

  // The date format of each declared date column (Third Party GDS — `date_formats`): what the
  // user chose, else what the file itself shows (`/detect-date-formats`), else the agency's
  // last upload's — components/statements/dateFormat.tsx `useDateFormats`, below.
  const dateFields = useMemo(() => std?.date_formats ?? [], [std]);
  const [lastUpload, setLastUpload] = useState<{ agencyKey: number | null; formats: Partial<DateFormats> } | null>(null);
  const [detected, setDetected] = useState<{ file: File; byField: Record<string, DetectedFormat> } | null>(null);
  const [detecting, setDetecting] = useState(false);
  const detectSeq = useRef(0);

  const asPage = layout === "page";
  // The upload step's second column: how to read the file, beside the file itself.
  const hasUploadSide = capturesPeriod || dateFields.length > 0 || captureControls;
  const [confirmLeave, setConfirmLeave] = useState(false);

  // Mapping
  const [search, setSearch] = useState("");

  // Review — sparse, keyed by the row's position in the file. Only what the user actually
  // changed is sent, so a 900-row statement carries three edits, not 900 rows of payload.
  const [edits, setEdits] = useState<Record<number, Record<string, string>>>({});
  const [page, setPage] = useState(0);

  // AI narration pass. `aiFields` is what makes the result visible — those fields have no
  // source column, so without it they would be written to `data` and never shown.
  // `aiFilled` is only for styling: it separates "the AI put this here" (purple) from "a
  // person typed this" (amber), and a human touch moves a cell from the first to the second.
  const [aiBusy, setAiBusy] = useState(false);
  const [aiFields, setAiFields] = useState<Set<string>>(new Set());
  const [aiFilled, setAiFilled] = useState<Record<number, Set<string>>>({});
  const [aiResult, setAiResult] = useState<AiParseResp | null>(null);

  // What is in the file (Third Party GDS). Asked of the server while the user reviews, through
  // the reading /confirm makes — mapping and edits applied — and asked again after each
  // change, because correcting a ticket number or an amount can turn a repeat into a new line.
  const [savePreview, setSavePreview] = useState<SavePreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewSeq = useRef(0);
  // What Save does with each bucket of duplicates, and — ticked on the grid — with single
  // rows. Applied here to the preview's marks, and sent with Save, which applies them again.
  const [dupChoices, setDupChoices] = useState<DupChoices>(DEFAULT_DUP_CHOICES);
  const [rowChoices, setRowChoices] = useState<Record<number, DupChoice>>({});
  // The file's duplicate rows → what kind, and what they repeat.
  const dupRows = useMemo(() => new Map(
    (savePreview?.rows ?? []).flatMap((r) => (r.index != null ? [[r.index, r] as const] : []))), [savePreview]);
  const earlierByBatch = useMemo(
    () => new Map((savePreview?.earlier ?? []).map((e) => [e.batch_id, e])), [savePreview]);
  /** Does Save write this file row? A new line always; a duplicate as chosen. */
  const willSave = (i: number): boolean => {
    const m = dupRows.get(i);
    return !m || (rowChoices[i] ?? dupChoices[m.kind]) === "save";
  };
  // Per bucket: the rows Save writes, and the rows ticked the other way from their bucket.
  const dupTally = useMemo(() => {
    const saved: Record<DupKind, number> = { exact: 0, partial: 0, in_file: 0 };
    const overridden: Record<DupKind, number> = { exact: 0, partial: 0, in_file: 0 };
    for (const r of savePreview?.rows ?? []) {
      const own = r.index != null ? rowChoices[r.index] : undefined;
      if ((own ?? dupChoices[r.kind]) === "save") saved[r.kind]++;
      if (own && own !== dupChoices[r.kind]) overridden[r.kind]++;
    }
    return { saved, overridden };
  }, [savePreview, dupChoices, rowChoices]);
  const entriesToSave = savePreview
    ? savePreview.counts.new + DUP_KINDS.reduce((s, k) => s + dupTally.saved[k], 0) : null;
  // Every entry left out: Save would write an empty statement, so it is not offered.
  const nothingToSave = !!savePreview && savePreview.total > 0 && entriesToSave === 0;
  const chooseBucket = (k: DupKind, c: DupChoice) => {
    setDupChoices((p) => ({ ...p, [k]: c }));
    // The bucket's answer is for every row of it — ticks made on the grid go.
    setRowChoices((p) => Object.fromEntries(Object.entries(p).filter(([i]) => dupRows.get(Number(i))?.kind !== k)));
  };
  const resetRows = (k: DupKind) => chooseBucket(k, dupChoices[k]);
  const toggleRow = (i: number, kind: DupKind) => {
    const next: DupChoice = willSave(i) ? "skip" : "save";
    setRowChoices((p) => {
      const n = { ...p };
      if (next === dupChoices[kind]) delete n[i]; else n[i] = next;
      return n;
    });
  };
  // Tickets dated outside the period (Third Party GDS) → which of their dates, and why.
  // Counted, marked and asked about only for the rows Save writes.
  const outsidePeriod = savePreview?.outside_period ?? null;
  const outsideRows = useMemo(
    () => new Map((outsidePeriod?.rows ?? []).map((r) => [r.index, r.outside])), [outsidePeriod]);
  // The statement's own balance lines, and rows with a value that could not be read.
  const balanceRows = useMemo(() => new Set(savePreview?.balance_rows ?? []), [savePreview]);
  const unparsedRows = useMemo(
    () => new Map((savePreview?.unparsed_rows ?? []).map((r) => [r.index, r.fields])), [savePreview]);
  // The Statement check's tile the grid is narrowed to.
  const [gridFilter, setGridFilter] = useState<GridFilter>("all");
  const outsideSaved = (outsidePeriod?.rows ?? []).filter((r) => willSave(r.index));
  // "Before you save" — asked at Save while the file holds duplicates or tickets dated outside.
  const [confirmSave, setConfirmSave] = useState(false);
  const needsConfirm = capturesPeriod && !!savePreview
    && (DUP_KINDS.some((k) => savePreview.counts[k] > 0) || outsideSaved.length > 0);
  // Excel dates put back in the sheet's format (Third Party GDS), by "row|file column".
  const dateFix = extracted?.date_fix ?? null;
  const fixedCells = useMemo(
    () => new Map((dateFix?.cells ?? []).map((c) => [`${c.index}|${c.column}`, c])), [dateFix]);

  useEffect(() => {
    api.get<StdResp>(`${apiBase}/standard-columns`)
      .then((r) => setStd(r.data))
      .catch(() => toast.error("Failed to load the column list."));
  }, [apiBase]);

  const allCols: StdCol[] = useMemo(
    () => (std?.groups ?? []).flatMap((g) => g.columns), [std]);
  const mappedCount = Object.values(columnMap).filter(Boolean).length;

  const missingRequired = (std?.required ?? [])
    .filter((g) => !g.fields.some((f) => columnMap[f]));
  const missingAdvisory = (std?.advisory ?? [])
    .filter((g) => !g.fields.some((f) => columnMap[f]));

  /** The rule the API enforces too — checked here so the user is not sent to the review
   *  step to build edits on a mapping that cannot be saved. */
  const checkMapping = (): boolean => {
    if (!missingRequired.length) return true;
    return notifyRequired(
      `Map ${missingRequired.map((g) => `${g.label} (${g.headers})`).join(" and ")} before continuing.`,
    );
  };

  // ── Upload ────────────────────────────────────────────────────────────────
  const pickFile = (f: File | null) => {
    if (f && !/\.(xlsx|xls|csv|tsv|txt)$/i.test(f.name)) {
      toast.error("Choose an .xlsx, .xls, .csv, .tsv or .txt file.");
      return;
    }
    setFile(f);
  };

  /** The period the file's name gives ("…01-07TH AUG 26.xlsx"), into the Statement period —
   *  else the email's, else the box is left empty and says so. Dates the user typed are kept;
   *  if the name then disagrees, it says what the name reads. */
  const guessPeriod = async (f: File) => {
    const seq = ++periodSeq.current;
    const typed = !periodGuessed && !!(periodFrom || periodTo);
    let found: { from: string; to: string } | null = null;
    try {
      const { data } = await api.get<{ period_from: string | null; period_to: string | null }>(
        `${apiBase}/period-guess`, { params: { file_name: f.name } });
      if (data.period_from && data.period_to) found = { from: data.period_from, to: data.period_to };
    } catch { /* the user can still type it */ }
    if (seq !== periodSeq.current) return;
    if (typed) {
      setPeriodNote(found && (found.from !== periodFrom || found.to !== periodTo)
        ? { tone: "ask", text: `The file name says ${formatPeriod(found.from, found.to)}.` } : null);
      return;
    }
    const fromEmail = !found && initialPeriod?.from && initialPeriod?.to
      ? { from: initialPeriod.from, to: initialPeriod.to } : null;
    const use = found ?? fromEmail;
    setPeriodFrom(use?.from ?? "");
    setPeriodTo(use?.to ?? "");
    setPeriodGuessed(!!use);
    setPeriodNote(use
      ? { tone: "ok", text: found ? "Read from the file name — check it." : "Read from the email — check it." }
      : { tone: "ask", text: "The file name doesn't say which days it covers — enter the period." });
  };

  // Once per file, and only once the column list says this type takes a period — the email
  // path hands the file over before that list has loaded.
  const guessedFor = useRef<File | null>(null);
  useEffect(() => {
    if (!capturesPeriod || !file || guessedFor.current === file) return;
    guessedFor.current = file;
    void guessPeriod(file);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capturesPeriod, file]);

  const typePeriod = (which: "from" | "to", value: string) => {
    periodSeq.current++;      // a guess still in flight must not overwrite what was typed
    if (which === "from") setPeriodFrom(value); else setPeriodTo(value);
    setPeriodGuessed(false);
    setPeriodNote(null);
  };
  const periodBackwards = !!periodFrom && !!periodTo && periodFrom > periodTo;

  // ── Date formats ──────────────────────────────────────────────────────────
  // Each column's format is, in order: what the user chose; what the file itself shows
  // (`/detect-date-formats` — e.g. "13/08/2026" can only be day-first, and a week of Booked
  // Dates lands in the statement period only one way round); the agency's last upload's; or,
  // when every date in the column is a real Excel date — which the format cannot change —
  // DD-MM-YYYY, said so. Anything else is left for the user to choose.

  // How the agency's last upload was read — a vendor writes its dates the same way each time.
  const agencyKey = requireSupplier ? agency?.id ?? null : null;
  useEffect(() => {
    if (!dateFields.length || (requireSupplier && agencyKey == null)) return;
    let live = true;
    api.get<{ date_formats: Partial<DateFormats> | null }>(`${apiBase}/last-date-formats`, {
      params: {
        ...(supplierId != null ? { supplier_id: supplierId } : {}),
        ...(agencyKey != null ? { agency_id: agencyKey } : {}),
      },
    })
      .then(({ data }) => { if (live) setLastUpload({ agencyKey, formats: data.date_formats ?? {} }); })
      .catch(() => { /* the file, or the user, decides */ });
    return () => { live = false; };
  }, [apiBase, dateFields, agencyKey, supplierId, requireSupplier]);

  // What the file shows — asked once it is chosen, and again when the period changes: the
  // period is what settles a date that reads both ways round.
  const detectPeriod = periodFrom && periodTo && !periodBackwards ? `${periodFrom}|${periodTo}` : "";
  useEffect(() => {
    if (!dateFields.length || !file) return;
    const seq = ++detectSeq.current;
    const timer = setTimeout(async () => {
      setDetecting(true);
      try {
        const fd = new FormData();
        fd.append("file", file);
        if (detectPeriod) {
          const [from, to] = detectPeriod.split("|");
          fd.append("period_from", from);
          fd.append("period_to", to);
        }
        const { data } = await api.post<{ fields: DetectedFormat[] }>(`${apiBase}/detect-date-formats`, fd);
        if (seq !== detectSeq.current) return;
        setDetected({ file, byField: Object.fromEntries(data.fields.map((d) => [d.field, d])) });
      } catch {
        if (seq === detectSeq.current) setDetected({ file, byField: {} });   // the user chooses
      } finally {
        if (seq === detectSeq.current) setDetecting(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [apiBase, dateFields, file, detectPeriod]);

  const fileDetection = detected && detected.file === file ? detected.byField : null;
  const lastFormats = lastUpload && lastUpload.agencyKey === agencyKey ? lastUpload.formats : null;
  const {
    formats: dateFormats, choose: chooseFormat, note: formatNote, missing: missingFormats,
    complete: formatsComplete, isAuto: formatsAuto,
  } = useDateFormats(dateFields, fileDetection, lastFormats, detecting,
    { lastUpload: "This agency's last upload", who: "this vendor" });

  // Date cells that did not fit their column's format, by "row|field" — from `/save-preview`.
  const unreadableDates = useMemo(
    () => new Map((savePreview?.dates ?? []).flatMap((d) =>
      d.cells.map((c) => [`${c.index}|${d.field}`, d] as const))),
    [savePreview]);

  /** "Next: map columns". File, agency and — Third Party GDS — the period are checked first;
   *  then the agency's uploads whose period overlaps this one are looked up, and if there
   *  are any the user is asked before the file is read ("already uploaded — Continue /
   *  Cancel"). Continuing compares the file with them; only what is new will be saved. */
  const startExtract = async () => {
    if (!file) { notifyRequired("Choose a statement file to continue."); return; }
    const agencyBlocked = requireSupplier ? agencyBlockReason(agency) : null;
    if (agencyBlocked) { notifyRequired(agencyBlocked); return; }
    if (missingFormats.length) {
      notifyRequired(`Choose the date format of ${missingFormats.map((f) => f.header).join(" and ")} — how your sheet writes its dates.`);
      return;
    }
    if (capturesPeriod) {
      if (!periodFrom || !periodTo) {
        notifyRequired("Enter the statement period — the days this statement covers (From and To).");
        return;
      }
      if (periodBackwards) { notifyRequired("The statement period's From date is after its To date."); return; }
      setCheckingPeriod(true);
      try {
        const { data } = await api.get<{ uploads: EarlierUpload[] }>(`${apiBase}/period-uploads`, {
          params: {
            period_from: periodFrom, period_to: periodTo,
            ...(supplierId != null ? { supplier_id: supplierId } : {}),
            ...(requireSupplier && agency ? { agency_id: agency.id } : {}),
          },
        });
        if (data.uploads.length) { setEarlier(data.uploads); return; }
      } catch (e) {
        toast.error(errMsg(e, "Could not check whether this period is already uploaded."));
        return;
      } finally { setCheckingPeriod(false); }
    }
    await doExtract();
  };

  const doExtract = async () => {
    if (!file) { notifyRequired("Choose a statement file to continue."); return; }
    const agencyBlocked = requireSupplier ? agencyBlockReason(agency) : null;
    if (agencyBlocked) { notifyRequired(agencyBlocked); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (supplierId != null) fd.append("supplier_id", String(supplierId));
      // The agency itself: channel-checked on the server, works while it awaits
      // approval, and carries the vendor service charge the SF columns are checked against.
      if (requireSupplier && agency) fd.append("agency_id", String(agency.id));
      // The period and the date formats decide how the Excel-stored dates are read — the same
      // reading /save-preview and /confirm make with them.
      if (capturesPeriod) {
        fd.append("period_from", periodFrom);
        fd.append("period_to", periodTo);
      }
      if (dateFields.length) fd.append("date_formats", JSON.stringify(dateFormats));
      const { data } = await api.post<ExtractResp>(`${apiBase}/extract`, fd);
      setExtracted(data);
      setColumnMap(data.suggested_mapping || {});
      setEdits({});
      setPage(0);
      setGridFilter("all");
      setDupChoices(DEFAULT_DUP_CHOICES);
      setRowChoices({});
      setStep("mapping");
    } catch (e) { toast.error(errMsg(e, "Could not read the file.")); }
    finally { setBusy(false); }
  };

  // ── Opened from an email ──────────────────────────────────────────────────
  // The file and the sender's agency are pre-filled; once both are known the wizard reads the
  // file itself, so the user's first screen is the mapping. An agency that cannot be used
  // (not found, awaiting supplier-master approval) leaves the user on the upload step to pick.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (initialFile) setFile(initialFile);
    if (initialControls?.count != null) setExpectedCount(String(initialControls.count));
    if (initialControls?.amount) setExpectedAmount(initialControls.amount);
    if (requireSupplier && initialAgencyId != null) {
      loadVendorAgencies()
        .then((list) => { const a = list.find((x) => x.id === initialAgencyId); if (a) setAgency(a); })
        .catch(() => { /* the picker loads its own list; the user can choose there */ });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!initialFile || autoStarted.current || step !== "upload" || !file || !std) return;
    if (requireSupplier && agencyBlockReason(agency)) return;
    // A period is needed first, read off the attachment's name or the email. Without one the
    // user stays here to enter it — and the dates they type never start it on their own.
    if (std.captures_period && !(periodFrom && periodTo && periodGuessed)) return;
    // Likewise the date formats: read off this file (or the agency's last upload) once the
    // file has been read for them, or the user picks them here.
    if (dateFields.length && !(formatsAuto && !detecting && detected?.file === file)) return;
    autoStarted.current = true;
    // The same path as Next: a period already uploaded is still asked about.
    void startExtract();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, agency, std, periodFrom, periodTo, periodGuessed, formatsAuto, detecting, detected]);

  // ── Mapping ───────────────────────────────────────────────────────────────
  const setMap = (field: string, col: string) =>
    setColumnMap((p) => { const n = { ...p }; if (col) n[field] = col; else delete n[field]; return n; });
  const autoMapAll = () => setColumnMap(extracted?.suggested_mapping || {});
  const clearAll = () => setColumnMap({});

  const filteredGroups: StdGroup[] = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return std?.groups ?? [];
    return (std?.groups ?? [])
      .map((g) => ({ ...g, columns: g.columns.filter((c) =>
        c.header.toLowerCase().includes(q) || c.field.toLowerCase().includes(q)) }))
      .filter((g) => g.columns.length > 0);
  }, [std, search]);

  // A source column used twice means one of the two fields is wrong — the user cannot see
  // that from a list of dropdowns, so it is called out rather than silently accepted.
  const duplicateSources = useMemo(() => {
    const seen: Record<string, string[]> = {};
    for (const [field, col] of Object.entries(columnMap)) {
      if (col) (seen[col] = seen[col] || []).push(field);
    }
    return Object.entries(seen).filter(([, fs]) => fs.length > 1);
  }, [columnMap]);

  // ── Review ────────────────────────────────────────────────────────────────
  // The fields worth showing: those a column was mapped onto, plus those the AI filled from
  // the narration. The second half is not cosmetic — an AI-filled field like `train_name`
  // has NO source column, so without it the value would be sent to the server, stored, and
  // never once be visible or editable on the screen that exists to review it.
  const reviewCols = useMemo(
    () => allCols.filter((c) => columnMap[c.field] || aiFields.has(c.field)),
    [allCols, columnMap, aiFields]);

  const valueAt = (r: SampleRow, field: string): string => {
    const edit = edits[r.__index__]?.[field];
    if (edit !== undefined) return edit;
    const src = columnMap[field];
    return (src ? r[src] : null) ?? "";
  };
  const isEdited = (r: SampleRow, field: string) => edits[r.__index__]?.[field] !== undefined;
  const isAiFilled = (r: SampleRow, field: string) => !!aiFilled[r.__index__]?.has(field);

  const setCell = (index: number, field: string, value: string, original: string) => {
    setEdits((p) => {
      const row = { ...(p[index] ?? {}) };
      // Typing a value back to what it was clears the edit rather than storing a no-op —
      // otherwise the "N rows edited" count lies.
      if (value === original) delete row[field];
      else row[field] = value;
      const n = { ...p };
      if (Object.keys(row).length) n[index] = row; else delete n[index];
      return n;
    });
    // Touching a cell makes it the user's, not the AI's — so it stops being purple. Done
    // here rather than in the renderer because the distinction is about who last wrote the
    // value, which only this handler knows.
    setAiFilled((p) => {
      const s = p[index];
      if (!s?.has(field)) return p;
      const next = new Set(s);
      next.delete(field);
      const n = { ...p };
      if (next.size) n[index] = next; else delete n[index];
      return n;
    });
  };

  // ── The AI narration pass ─────────────────────────────────────────────────
  const aiCfg = extracted?.ai_narration ?? null;
  const aiSourceCol = aiCfg ? columnMap[aiCfg.source_field] : undefined;

  const runAi = async () => {
    if (!extracted || !aiCfg || !aiSourceCol) return;
    const payload = extracted.sample_rows
      .map((r) => ({
        index: r.__index__,
        text: valueAt(r, aiCfg.source_field),
        product_type: valueAt(r, "product_type") || null,
      }))
      .filter((r) => r.text.trim());
    if (!payload.length) {
      toast.error(`No ${aiCfg.label} text to read — every row's ${aiCfg.label} is empty.`);
      return;
    }
    setAiBusy(true);
    try {
      // Per-call, not on the shared client: a global timeout this long would also apply to
      // /confirm, which is the slower request on a large sheet.
      const { data } = await api.post<AiParseResp>(
        `${apiBase}/ai-parse`,
        { rows: payload, source_format: extracted.source_format ?? null },
        { timeout: 300_000 },
      );
      // Merged against the CURRENT edits, then both pieces of state are set from the
      // result. Deliberately not one nested updater: React may invoke an updater twice,
      // and a setState nested inside one would then apply its effect twice.
      const nextEdits = { ...edits };
      const nextFilled: Record<number, Set<string>> = { ...aiFilled };
      for (const [key, vals] of Object.entries(data.rows)) {
        const i = Number(key);
        const row = { ...(nextEdits[i] ?? {}) };
        const marks = new Set(nextFilled[i] ?? []);
        for (const [f, v] of Object.entries(vals)) {
          if (v == null || v === "") continue;
          // A value the person already corrected always wins over the model's reading.
          if (row[f] !== undefined) continue;
          row[f] = String(v);
          marks.add(f);
        }
        if (Object.keys(row).length) nextEdits[i] = row;
        if (marks.size) nextFilled[i] = marks;
      }
      setAiResult(data);
      setAiFields(new Set(data.fields));
      setEdits(nextEdits);
      setAiFilled(nextFilled);
      setPage(0);
      if (data.warning) toast(data.warning, { icon: "⚠️" });
      else toast.success(`Read ${data.parsed_rows} of ${data.requested_rows} ${aiCfg.label}s.`);
    } catch (e) {
      toast.error(errMsg(e, "The AI pass could not be completed. Nothing was changed."));
    } finally { setAiBusy(false); }
  };

  const editedRowCount = Object.keys(edits).length;
  const rows = useMemo(() => extracted?.sample_rows ?? [], [extracted]);
  // ── The Statement check (Third Party GDS) ─────────────────────────────────
  // Each count narrows the grid to its rows. A row leaves its filter once it is put right —
  // a date corrected into the period drops out of "After period" at the next check — and an
  // emptied filter says so rather than falling back to every row.
  const sides = (i: number): OutsideSide[] => (willSave(i) ? Object.values(outsideRows.get(i) ?? {}) : []);
  const inFilter = (i: number): boolean => {
    switch (gridFilter) {
      case "exact": case "partial": case "in_file": return dupRows.get(i)?.kind === gridFilter;
      case "new": return !dupRows.has(i) && !balanceRows.has(i);
      case "before": return sides(i).includes("before");
      case "after": return sides(i).includes("after");
      case "unparsed": return unparsedRows.has(i);
      case "edited": return !!edits[i];
      default: return true;
    }
  };
  // A row ticked out of the save leaves Before / After at once, like a date corrected into
  // the period — so those two follow the choices too.
  const shownRows = useMemo(
    () => (gridFilter === "all" ? rows : rows.filter((r) => inFilter(r.__index__))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, gridFilter, dupRows, balanceRows, outsideRows, unparsedRows, edits, dupChoices, rowChoices]);
  const pickFilter = (f: GridFilter) => { setGridFilter(f); setPage(0); };
  const sideCount = (side: OutsideSide) =>
    outsideSaved.filter((r) => Object.values(r.outside).includes(side)).length;
  const checkCounts: Record<GridFilter, number | null> = {
    all: savePreview ? savePreview.total : null,
    exact: savePreview ? savePreview.counts.exact : null,
    partial: savePreview ? savePreview.counts.partial : null,
    in_file: savePreview ? savePreview.counts.in_file : null,
    new: savePreview ? savePreview.counts.new : null,
    before: outsidePeriod ? sideCount("before") : null,
    after: outsidePeriod ? sideCount("after") : null,
    unparsed: savePreview ? savePreview.unparsed_rows?.length ?? 0 : null,
    edited: editedRowCount,
  };
  /** A duplicate tile's second line: what Save does with the bucket as chosen. */
  const dupHint = (k: DupKind): string => {
    const n = savePreview?.counts[k] ?? 0;
    const s = dupTally.saved[k];
    if (!n) return { exact: "already saved", partial: "same ticket, changed", in_file: "same ticket twice" }[k];
    if (s === 0) return "not saved";
    if (s === n) return k === "exact" ? "saved again" : "saved, flagged";
    return `${s} saved · ${n - s} not`;
  };
  const pageCount = Math.max(1, Math.ceil(shownRows.length / PAGE));
  const curPage = Math.min(page, pageCount - 1);
  const pageRows = shownRows.slice(curPage * PAGE, curPage * PAGE + PAGE);
  const datesMapped = !!(columnMap.booking_date || columnMap.issue_date);
  // A filter's rows past the editable preview: counted on its tile, not in the grid.
  const filteredPastPreview = gridFilter !== "all" && checkCounts[gridFilter] != null
    ? Math.max(0, (checkCounts[gridFilter] ?? 0) - shownRows.length) : 0;

  // The lines under the counts — what Save will do, and what needs a look.
  const checkNotes: CheckNote[] = [];
  const periodText = savePreview?.period_label ?? (periodFrom && periodTo ? formatPeriod(periodFrom, periodTo) : "");
  if (previewError) checkNotes.push({ tone: "warn", text: previewError });
  if (nothingToSave) {
    checkNotes.push({ tone: "bad", text: <><strong>Nothing will be saved</strong> — every entry is left out as a
      duplicate. Choose <strong>Save again</strong> above to save them anyway.</> });
  }
  if (savePreview && !DUP_KINDS.some((k) => savePreview.counts[k])) {
    checkNotes.push({ tone: "ok", text: "Checked against every statement saved for this agency — nothing in this file is saved yet." });
  }
  for (const e of savePreview?.earlier ?? []) {
    const parts = [
      e.exact ? `${e.exact.toLocaleString("en-IN")} already uploaded` : null,
      e.partial ? `${e.partial.toLocaleString("en-IN")} partial duplicate${e.partial === 1 ? "" : "s"}` : null,
    ].filter(Boolean);
    checkNotes.push({ tone: "info", text: <>Matches {earlierName(e)} — <strong>{parts.join(", ")}</strong>.</> });
  }
  if (savePreview?.week_outside.length) {
    checkNotes.push({ tone: "warn", text: <>The file&apos;s Week column says{" "}
      {savePreview.week_outside.map((w) => `"${w.week}" (${w.rows} row${w.rows === 1 ? "" : "s"})`).join(", ")} —
      outside {periodText}. Check the period on the Upload step.</> });
  }
  if (dateFix) {
    checkNotes.push({ tone: "fix", text: `${dateFix.count.toLocaleString("en-IN")} Excel dates read as `
      + `${orderLabel(dateFormats.booking_date)} — Excel had stored them with day and month swapped. Blue in the grid.` });
  }
  for (const d of savePreview?.dates ?? []) {
    if (!d.unreadable) continue;
    const shown = d.cells.slice(0, 3).map((c) => `"${c.value ?? ""}" (row ${c.index + 1})`).join(", ");
    checkNotes.push({ tone: "warn", text: <>{d.unreadable.toLocaleString("en-IN")} {d.header}{" "}
      value{d.unreadable === 1 ? "" : "s"} can&apos;t be read as {orderLabel(d.format ?? undefined)}: {shown}
      {d.unreadable > 3 ? ", …" : ""}. If they are all like that, pick another format; otherwise correct them
      under <strong>Not read</strong>.</> });
  }
  if (capturesPeriod && !datesMapped) {
    checkNotes.push({ tone: "warn", text: "Booked Date and Issue Date aren't mapped, so the tickets can't be checked against the period." });
  }

  // ── Rows the import will skip ─────────────────────────────────────────────
  // Recomputed from the CURRENT mapping and edits, not from the extract response, so
  // remapping TXN Type or correcting one in a cell moves the row in or out of the grey
  // immediately — which is the only way the user can tell the rule is reading the column
  // they think it is. Only ever covers the previewed rows; the footer says the rest of the
  // file is filtered too.
  const rowFilter = std?.row_filter ?? null;
  const filterMapped = !!rowFilter && !!columnMap[rowFilter.field];
  const isSkipped = (r: SampleRow): boolean => {
    if (!rowFilter || !filterMapped) return false;
    const v = valueAt(r, rowFilter.field).trim();
    return v !== "" && rowFilter.exclude.includes(normTxn(v));
  };
  const skippedPreview = useMemo(
    () => (rowFilter && filterMapped ? rows.filter(isSkipped).length : 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, rowFilter, filterMapped, columnMap, edits],
  );

  useEffect(() => {
    if (step !== "review" || !capturesPeriod || !extracted || !file) return;
    // Only the latest answer counts: an edit made while a check is in flight starts another.
    const seq = ++previewSeq.current;
    setPreviewBusy(true);
    const timer = setTimeout(async () => {
      try {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("column_map", JSON.stringify(columnMap));
        if (supplierId != null) fd.append("supplier_id", String(supplierId));
        if (requireSupplier && agency) fd.append("agency_id", String(agency.id));
        fd.append("header_row", String(extracted.header_row));
        fd.append("file_digest", extracted.file_digest);
        fd.append("edits", JSON.stringify(edits));
        fd.append("period_from", periodFrom);
        fd.append("period_to", periodTo);
        if (dateFields.length) fd.append("date_formats", JSON.stringify(dateFormats));
        const { data } = await api.post<SavePreview & { applies: boolean }>(`${apiBase}/save-preview`, fd);
        if (seq !== previewSeq.current) return;
        setSavePreview(data.applies ? data : null);
        setPreviewError(null);
      } catch (e) {
        if (seq !== previewSeq.current) return;
        setSavePreview(null);
        setPreviewError(errMsg(e, "Could not check this file against the period's earlier uploads. Saving will still check it."));
      } finally {
        if (seq === previewSeq.current) setPreviewBusy(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [step, capturesPeriod, extracted, file, columnMap, edits, agency, supplierId, requireSupplier, apiBase,
      periodFrom, periodTo, dateFields, dateFormats]);

  // ── Save ──────────────────────────────────────────────────────────────────
  const doConfirm = async () => {
    if (!extracted || !file) { notifyRequired("Nothing to save — upload a file first."); return; }
    // Re-checked here, not only on the Next button: this is the call that writes rows and
    // the user can reach it after going back and editing the mapping.
    if (!checkMapping()) { setStep("mapping"); return; }
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("column_map", JSON.stringify(columnMap));
      if (supplierId != null) fd.append("supplier_id", String(supplierId));
      // The agency itself: channel-checked on the server, works while it awaits
      // approval, and carries the vendor service charge the SF columns are checked against.
      if (requireSupplier && agency) fd.append("agency_id", String(agency.id));
      fd.append("header_row", String(extracted.header_row));
      fd.append("file_digest", extracted.file_digest);
      fd.append("edits", JSON.stringify(edits));
      if (capturesPeriod) {
        fd.append("period_from", periodFrom);
        fd.append("period_to", periodTo);
        // What to do with the duplicates — per bucket, and the rows ticked on the grid that
        // are still duplicates. The server screens the file again and applies them.
        const rowsChosen = Object.fromEntries(Object.entries(rowChoices).filter(([i]) => dupRows.has(Number(i))));
        fd.append("duplicate_choices", JSON.stringify({ ...dupChoices, rows: rowsChosen }));
      }
      if (dateFields.length) fd.append("date_formats", JSON.stringify(dateFormats));
      if (captureControls) {
        const count = parseInt(expectedCount.replace(/[^\d]/g, ""), 10);
        if (count > 0) fd.append("expected_count", String(count));
        const amount = expectedAmount.replace(/[,\s₹]/g, "");
        if (amount) fd.append("expected_amount", amount);
      }
      const { data } = await api.post<SaveResp>(`${apiBase}/confirm`, fd);
      setSaved(data);
      setStep("done");
    } catch (e) { toast.error(errMsg(e, "Could not save the statement.")); }
    finally { setSaving(false); }
  };

  // ── Leaving (page layout) ─────────────────────────────────────────────────
  // Mid-mapping or mid-review, leaving loses the mapping and every correction: the page asks
  // first, and a refresh or a closed tab gets the browser's own question.
  const inProgress = step === "mapping" || step === "review";
  const leave = () => (asPage && inProgress ? setConfirmLeave(true) : onClose());
  useEffect(() => {
    if (!asPage || !inProgress) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [asPage, inProgress]);

  // ── render ────────────────────────────────────────────────────────────────
  const truncated = !!extracted && extracted.total_rows > extracted.preview_rows;

  return (
    <div className={asPage ? "w-full" : "fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"}>
      <div className={asPage
        ? "bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col"
        : "bg-white rounded-xl shadow-xl w-full max-w-5xl max-h-[92vh] flex flex-col"}>
        {asPage ? (
          // One bar for the way back, the title and the steps — the page keeps its height
          // for the form.
          <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-2.5 border-b border-slate-100 bg-slate-50/60 rounded-t-xl">
            <div className="flex items-center gap-3 min-w-0">
              <button onClick={leave}
                className="inline-flex items-center gap-1.5 shrink-0 text-xs font-medium text-slate-500 hover:text-slate-800">
                <ArrowLeft className="w-3.5 h-3.5" /> {backLabel ?? "Back to uploads"}
              </button>
              <span className="h-4 w-px bg-slate-200 shrink-0" />
              <h2 className="text-sm font-semibold text-slate-800 truncate">Upload {title} statement</h2>
            </div>
            <StepBar step={step} inline />
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-800">Upload {title} statement</h2>
              <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
                <X className="w-4 h-4" />
              </button>
            </div>
            <StepBar step={step} />
          </>
        )}

        <div className={asPage ? "p-4" : "flex-1 overflow-y-auto p-5"}>
          {/* ── 1. Upload ─────────────────────────────────────────────────── */}
          {step === "upload" && (
            <>
              {/* On a page: what the statement is (agency, file) beside how to read it (period,
                  date format, controls), so the whole step fits without scrolling. Stacked in
                  the popup. */}
              <div className={asPage && hasUploadSide ? "grid gap-4 lg:grid-cols-2 items-start" : "space-y-4"}>
                <div className="space-y-4">
                  {/* Agency FIRST: it decides which B2B deal prices the statement, and a
                      wrong pick is not visible anywhere later. The values are rows in the
                      user's own Agency Master. */}
                  {requireSupplier && (
                    <StatementAgencyField value={agency} onChange={setAgency}
                      channel={channelForApiBase(apiBase)} />
                  )}

                  <div
                    onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0] ?? null); }}
                    onClick={() => !file && inputRef.current?.click()}
                    className={`cursor-pointer flex flex-col items-center justify-center rounded-xl border-2 border-dashed ${asPage ? "p-6" : "p-8"} text-center ${
                      dragging ? "border-blue-500 bg-blue-50"
                        : file ? "border-emerald-200 bg-emerald-50/40"
                        : "border-slate-200 bg-slate-50/60 hover:border-slate-300"}`}
                  >
                    {file ? (
                      <div className="w-full max-w-sm flex items-center gap-3 rounded-lg border border-emerald-200 bg-white p-3 shadow-sm">
                        <div className="w-9 h-9 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0">
                          <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
                        </div>
                        <div className="min-w-0 flex-1 text-left">
                          <p className="text-xs font-semibold text-slate-800 truncate" title={file.name}>{file.name}</p>
                          <p className="text-[11px] text-slate-500">{(file.size / 1024).toFixed(0)} KB</p>
                        </div>
                        <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
                        <button onClick={(e) => { e.stopPropagation(); setFile(null); }}
                          className="p-1 text-slate-400 hover:text-red-500 shrink-0"><X className="w-4 h-4" /></button>
                      </div>
                    ) : (
                      <>
                        <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mb-3">
                          <Upload className="w-6 h-6 text-blue-600" />
                        </div>
                        <p className="text-sm font-medium text-slate-700">Drop your {title} export here</p>
                        <p className="text-xs text-slate-400 mt-0.5">or click to browse · .xlsx, .xls, .csv, .tsv</p>
                      </>
                    )}
                    <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv,.tsv,.txt"
                      className="hidden" onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
                  </div>
                </div>

                {hasUploadSide && (
                  <div className="space-y-4">
                    {/* The days the statement covers: its tickets are checked against them, and a
                        period already uploaded for this agency is asked about before reading.
                        Read off the file name where it says; asked for where it does not. */}
                    {capturesPeriod && (
                      <div className={`rounded-lg border p-3 ${
                        periodBackwards ? "border-red-200 bg-red-50/40" : "border-slate-200"}`}>
                        <p className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
                          <CalendarRange className="w-3.5 h-3.5 text-slate-400" />
                          Statement period <span className="text-red-500">*</span>
                        </p>
                        <p className="text-[11px] text-slate-400 mt-0.5">
                          The days this statement covers. Tickets booked or issued outside it are flagged
                          for you to review before saving. Every entry is also checked against this
                          agency&apos;s earlier statements — duplicates are shown before anything is saved.
                        </p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">
                          <label className="block">
                            <span className="text-[11px] text-slate-500">From</span>
                            <input type="date" value={periodFrom} max={periodTo || undefined}
                              onChange={(e) => typePeriod("from", e.target.value)}
                              onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
                              className="mt-1 w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
                          </label>
                          <label className="block">
                            <span className="text-[11px] text-slate-500">To</span>
                            <input type="date" value={periodTo} min={periodFrom || undefined}
                              onChange={(e) => typePeriod("to", e.target.value)}
                              onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch {} }}
                              className="mt-1 w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
                          </label>
                        </div>
                        {periodBackwards ? (
                          <p className="text-[11px] text-red-500 mt-1.5">From must be on or before To.</p>
                        ) : periodNote ? (
                          <p className={`text-[11px] mt-1.5 ${periodNote.tone === "ok" ? "text-emerald-600" : "text-amber-600"}`}>
                            {periodNote.tone === "ok" && periodFrom && periodTo
                              ? <><strong>{formatPeriod(periodFrom, periodTo)}</strong> — {periodNote.text}</>
                              : periodNote.text}
                          </p>
                        ) : periodFrom && periodTo ? (
                          <p className="text-[11px] text-slate-500 mt-1.5">{formatPeriod(periodFrom, periodTo)}</p>
                        ) : null}
                      </div>
                    )}

                    {/* How the sheet writes its dates. Read off the file where it shows it
                        ("05/08/2026" is valid both ways; the period settles it), else the
                        agency's last upload — and asked where neither says. */}
                    {dateFields.length > 0 && (
                      <div className="rounded-lg border border-slate-200 p-3">
                        <DateFormatSection fields={dateFields} formats={dateFormats} onChoose={chooseFormat}
                          note={formatNote} detecting={detecting} />
                      </div>
                    )}

                    {captureControls && (
                      <div className="rounded-lg border border-slate-200 p-3">
                        <p className="text-xs font-semibold text-slate-700">Control totals <span className="font-normal text-slate-400">(optional)</span></p>
                        <p className="text-[11px] text-slate-400 mt-0.5">
                          What the statement should hold — from the vendor&apos;s covering note. The upload is
                          checked against them, alongside the statement&apos;s own opening and closing balance.
                        </p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">
                          <label className="block">
                            <span className="text-[11px] text-slate-500">Expected records (tickets)</span>
                            <input value={expectedCount} onChange={(e) => setExpectedCount(e.target.value)}
                              inputMode="numeric" placeholder="e.g. 37"
                              className="mt-1 w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
                          </label>
                          <label className="block">
                            <span className="text-[11px] text-slate-500">Expected net amount (₹)</span>
                            <input value={expectedAmount} onChange={(e) => setExpectedAmount(e.target.value)}
                              inputMode="decimal" placeholder="e.g. 3,33,171.43"
                              className="mt-1 w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
                          </label>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <p className="text-[11px] text-slate-400 mt-3">
                Any layout works — you will map the columns on the next step. Press
                <strong> Template</strong> on the previous screen for a sheet that maps itself.
              </p>
            </>
          )}

          {/* ── 2. Map columns ────────────────────────────────────────────── */}
          {step === "mapping" && extracted && (
            <>
              {/* Only the multi-vendor types report a format at all. Shown, never editable:
                  the mapping below IS the parser, so a dropdown here would let the label
                  and the actual reading disagree with nothing to reconcile them. */}
              {extracted.detects_format && (
                <div className={`flex items-start gap-2 px-3 py-2.5 mb-3 rounded-xl border text-xs ${
                  extracted.source_format_label
                    ? "border-violet-200 bg-violet-50 text-violet-800"
                    : "border-slate-200 bg-slate-50 text-slate-600"}`}>
                  <Sparkles className="w-4 h-4 shrink-0 mt-px" />
                  <span>
                    {extracted.source_format_label ? (
                      <><strong>Detected: a {extracted.source_format_label} statement.</strong>{" "}
                        The mapping below is already set to that vendor&apos;s columns.</>
                    ) : (
                      <><strong>Vendor not recognised.</strong> The rows still import — they
                        just won&apos;t carry a vendor label. Map the columns below as usual.</>
                    )}
                  </span>
                </div>
              )}
              {dateFix && <DateFixNote fix={dateFix} format={orderLabel(dateFormats.booking_date)} />}
              <div className={`flex items-start gap-2 px-3 py-2 mb-3 rounded-xl border text-xs ${
                extracted.is_template_match || extracted.matched_columns >= extracted.columns.length
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                  : "border-sky-200 bg-sky-50 text-sky-800"}`}>
                {extracted.is_template_match || extracted.matched_columns >= extracted.columns.length
                  ? <CheckCircle2 className="w-4 h-4 shrink-0 mt-px" />
                  : <Wand2 className="w-4 h-4 shrink-0 mt-px" />}
                <span>
                  {extracted.is_template_match ? (
                    <><strong>This file matches the template.</strong> All {extracted.matched_columns} columns
                      were recognised — check them if you like, then continue.</>
                  ) : extracted.matched_columns >= extracted.columns.length ? (
                    // Every column of the file is mapped; what is left over are standard fields
                    // this export simply does not have, and there is nothing to set.
                    <><strong>All {extracted.columns.length} columns in your file were recognised.</strong>{" "}
                      Check the mapping below, then continue — fields left as <em>not in file</em> aren&apos;t
                      in this export.</>
                  ) : (
                    <><strong>{extracted.matched_columns} of {extracted.columns.length} columns
                      were recognised by name.</strong> Map the rest below — anything left as
                      <em> not in file</em> isn&apos;t imported.</>
                  )}
                </span>
              </div>

              {missingRequired.length > 0 && (
                <div className="flex items-start gap-2 px-3 py-2.5 mb-3 rounded-xl border border-red-200 bg-red-50 text-xs text-red-700">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />
                  <span>
                    <strong>Still needed: {missingRequired.map((g) => g.label).join(" and ")}.</strong>{" "}
                    {missingRequired.map((g) => g.headers).join("; ")}. Without these a row cannot
                    be found in Ticket Search or reconciled against anything.
                  </span>
                </div>
              )}
              {missingRequired.length === 0 && missingAdvisory.length > 0 && (
                <div className="flex items-start gap-2 px-3 py-2.5 mb-3 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />
                  <span>
                    <strong>You can save without {missingAdvisory.map((g) => g.label).join(" or ")},
                    but Commission income will not price these rows.</strong>{" "}
                    {missingAdvisory.map((g) => g.consequence).filter(Boolean).join(" ")}
                  </span>
                </div>
              )}
              {duplicateSources.length > 0 && (
                <div className="flex items-start gap-2 px-3 py-2.5 mb-3 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />
                  <span>
                    <strong>One column is mapped to more than one field.</strong>{" "}
                    {duplicateSources.map(([col, fields]) => `“${col}” → ${fields.join(", ")}`).join("; ")}.
                    That is allowed, but it is usually a mistake.
                  </span>
                </div>
              )}

              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                  <input value={search} onChange={(e) => setSearch(e.target.value)}
                    placeholder="Find a field…"
                    className="pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-lg w-56 focus:outline-none focus:ring-1 focus:ring-blue-400" />
                </div>
                <button onClick={autoMapAll}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50">
                  <Wand2 className="w-3.5 h-3.5" /> Auto-map
                </button>
                <button onClick={clearAll}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
                  <Eraser className="w-3.5 h-3.5" /> Clear all
                </button>
                <span className="ml-auto text-[11px] text-slate-400">
                  {mappedCount} of {std?.total ?? 0} fields mapped
                </span>
              </div>

              <div className="space-y-4">
                {filteredGroups.map((g) => (
                  <div key={g.group}>
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">{g.group}</p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {g.columns.map((c) => {
                        const required = (std?.required ?? []).some((r) => r.fields.includes(c.field));
                        return (
                          <div key={c.field} className="flex items-center gap-2">
                            <label className="text-xs text-slate-600 w-40 shrink-0 truncate" title={c.field}>
                              {c.header}
                              {required && <span className="text-red-400 ml-0.5">*</span>}
                            </label>
                            <select
                              value={columnMap[c.field] ?? SKIP}
                              onChange={(e) => setMap(c.field, e.target.value)}
                              className={`flex-1 min-w-0 border rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                                columnMap[c.field] ? "border-slate-200 text-slate-700" : "border-slate-200 text-slate-400"}`}
                            >
                              <option value={SKIP}>— not in file —</option>
                              {extracted.columns.map((col) => (
                                <option key={col} value={col}>{col}</option>
                              ))}
                            </select>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* ── 3. Review & edit ──────────────────────────────────────────── */}
          {step === "review" && extracted && (
            <>
              {/* Third Party GDS: one box — the counts, each a filter on the grid below; how
                  the dates read, in which format; and the few things that need a look. */}
              {capturesPeriod && (
                <ReviewSummary counts={checkCounts} balanceLines={savePreview?.balance_lines ?? 0}
                  hints={{ exact: dupHint("exact"), partial: dupHint("partial"), in_file: dupHint("in_file") }}
                  filter={gridFilter} onFilter={pickFilter} periodLabel={periodText}
                  busy={previewBusy} dates={savePreview?.dates ?? []} formats={dateFormats}
                  onFormat={chooseFormat} notes={checkNotes}>
                  {savePreview && (
                    <DuplicateChoices counts={savePreview.counts} net={savePreview.net} choices={dupChoices}
                      onChoose={chooseBucket} overridden={dupTally.overridden} onReset={resetRows}
                      earlier={savePreview.earlier} />
                  )}
                </ReviewSummary>
              )}

              {/* What this type throws away, said before it happens. Without it the only
                  evidence is an entry count lower than the file's row count, discovered
                  later on a screen that cannot explain it. */}
              {rowFilter && (
                <div className={`flex items-start gap-2 px-3 py-2.5 mb-3 rounded-xl border text-xs ${
                  filterMapped
                    ? "border-slate-200 bg-white text-slate-600"
                    : "border-amber-200 bg-amber-50 text-amber-800"}`}>
                  <Filter className={`w-4 h-4 shrink-0 mt-px ${filterMapped ? "text-slate-400" : "text-amber-500"}`} />
                  {filterMapped ? (
                    <span>
                      <strong>
                        {skippedPreview > 0
                          ? `${skippedPreview.toLocaleString("en-IN")} of the ${rows.length.toLocaleString("en-IN")} rows shown will be skipped`
                          : "No rows shown will be skipped"}
                      </strong>{" "}
                      — {rowFilter.note} Skipped rows are greyed out below.{" "}
                      <span className="text-slate-400">
                        Kept: {rowFilter.keep.join(", ")}. Dropped: {rowFilter.exclude.join(", ")}.
                      </span>
                      {truncated && <> The same rule applies to the rows past the preview.</>}
                    </span>
                  ) : (
                    <span>
                      <strong>{rowFilter.header} isn&apos;t mapped</strong>, so {rowFilter.label} cannot
                      be identified and <strong>every row will import</strong>. Go back and map it if
                      your file has that column.
                    </span>
                  )}
                </div>
              )}

              {reviewCols.length === 0 ? (
                <p className="text-xs text-slate-400 py-10 text-center">
                  Nothing is mapped yet — go back and map at least one column.
                </p>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2 text-[11px] text-slate-400">
                    <span>
                      {rows.length.toLocaleString("en-IN")} row{rows.length === 1 ? "" : "s"} ·{" "}
                      {reviewCols.length} column{reviewCols.length === 1 ? "" : "s"}
                    </span>
                    <span className="inline-flex items-center gap-1 text-slate-500"
                      title={dateFields.length > 0
                        ? "Amounts are normalised after you edit (1,23,456.78 is fine); a date is read in its column's format, so type it the way the sheet does."
                        : "Dates and amounts are normalised after you edit — 13-08-2026 or 1,23,456.78 is fine."}>
                      <Pencil className="w-3 h-3" /> Click any cell to correct it
                    </span>
                    {truncated && (
                      <span className="text-amber-600">
                        First {extracted.preview_rows.toLocaleString("en-IN")} of{" "}
                        {extracted.total_rows.toLocaleString("en-IN")} rows shown — the rest import as mapped
                      </span>
                    )}
                    {gridFilter !== "all" && (
                      <span className="inline-flex items-center gap-1 text-blue-700 font-semibold">
                        <Filter className="w-3 h-3" /> {FILTER_LABEL[gridFilter]}: {shownRows.length.toLocaleString("en-IN")}{" "}
                        row{shownRows.length === 1 ? "" : "s"}
                        {filteredPastPreview > 0 && (
                          <span className="font-normal text-slate-400">
                            {" "}(+{filteredPastPreview.toLocaleString("en-IN")} past the rows shown)
                          </span>
                        )}
                        <button onClick={() => pickFilter("all")}
                          className="ml-1 text-slate-400 hover:text-slate-700 font-medium">
                          show all
                        </button>
                      </span>
                    )}
                    {editedRowCount > 0 && (
                      <span className="inline-flex items-center gap-1 text-amber-700 font-semibold">
                        <Pencil className="w-3 h-3" /> {editedRowCount} row{editedRowCount === 1 ? "" : "s"} edited
                        <button onClick={() => { setEdits({}); setAiFilled({}); setAiFields(new Set()); setAiResult(null); }}
                          className="ml-1 inline-flex items-center gap-1 text-slate-400 hover:text-slate-700 font-medium">
                          <RotateCcw className="w-3 h-3" /> undo all
                        </button>
                      </span>
                    )}
                    {/* Only the types that declare a free-text field get this at all, and
                        only once that field is actually mapped — there is nothing to read
                        otherwise, and a button that can only fail is worse than no button. */}
                    {aiCfg && (
                      <button
                        onClick={runAi}
                        disabled={aiBusy || !aiSourceCol}
                        title={aiSourceCol
                          ? `Read the ${aiCfg.label} column and fill in the fields written inside it.`
                          : `Map the ${aiCfg.label} column first — there is nothing to read yet.`}
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border font-semibold transition-colors ${
                          aiBusy || !aiSourceCol
                            ? "border-slate-200 text-slate-300 cursor-not-allowed"
                            : "border-violet-200 bg-violet-50 text-violet-700 hover:bg-violet-100"}`}
                      >
                        <Sparkles className={`w-3 h-3 ${aiBusy ? "animate-pulse" : ""}`} />
                        {aiBusy ? "Reading…" : "AI Analysis"}
                      </button>
                    )}
                    {aiResult && !aiBusy && (
                      <span className="inline-flex items-center gap-1 text-violet-700 font-semibold">
                        {aiResult.parsed_rows} of {aiResult.requested_rows} read
                      </span>
                    )}
                    <span className="ml-auto">Page {curPage + 1} of {pageCount}</span>
                  </div>

                  {aiResult && aiResult.fields.length > 0 && (
                    <div className="flex items-start gap-2 px-3 py-2.5 mb-2 rounded-xl border border-violet-200 bg-violet-50 text-xs text-violet-800">
                      <Sparkles className="w-4 h-4 shrink-0 mt-px" />
                      <span>
                        <strong>{aiResult.fields.length} field{aiResult.fields.length === 1 ? "" : "s"} were
                        read out of the {aiCfg?.label}</strong> and added as new columns, shown in violet.
                        They are ordinary cells — check them, correct anything wrong, and they save with
                        the rest. {aiResult.warning}
                      </span>
                    </div>
                  )}

                  <div className="border border-slate-200 rounded-xl overflow-hidden">
                    <div className={`overflow-x-auto ${asPage ? "max-h-[62vh]" : "max-h-[46vh]"}`}>
                      <table className="w-full text-xs">
                        <thead className="sticky top-0">
                          <tr className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400 whitespace-nowrap">
                            <th className="text-left px-2 py-2 font-semibold w-10">#</th>
                            {reviewCols.map((c) => {
                              const fromAi = !columnMap[c.field] && aiFields.has(c.field);
                              return (
                                <th key={c.field}
                                    className={`text-left px-2 py-2 font-semibold ${fromAi ? "text-violet-500" : ""}`}
                                    title={fromAi
                                      ? `${c.field} ← read from the ${aiCfg?.label}`
                                      : `${c.field} ← ${columnMap[c.field]}`}>
                                  {c.header}
                                </th>
                              );
                            })}
                          </tr>
                        </thead>
                        <tbody>
                          {pageRows.length === 0 && gridFilter !== "all" && (
                            <tr>
                              <td colSpan={reviewCols.length + 1} className="px-3 py-10 text-center text-slate-400">
                                No rows left under <strong className="text-slate-600">{FILTER_LABEL[gridFilter]}</strong>
                                {filteredPastPreview > 0 ? " among the rows shown" : ""}.{" "}
                                <button onClick={() => pickFilter("all")} className="text-blue-600 hover:underline">
                                  Show all rows
                                </button>
                              </td>
                            </tr>
                          )}
                          {pageRows.map((r) => {
                          // Still editable, deliberately: the way out of the grey is to fix
                          // the TXN Type cell, and a disabled input would make the row look
                          // like a dead end.
                          const skipped = isSkipped(r);
                          // A duplicate (Third Party GDS): tagged with its kind and what it
                          // repeats, ticked while Save writes it — greyed, like a skipped
                          // row, once it is left out.
                          const dup = skipped ? undefined : dupRows.get(r.__index__);
                          const leftOut = !!dup && !willSave(r.__index__);
                          const twin = dup?.batch_id ? earlierByBatch.get(dup.batch_id) : undefined;
                          // The cells that differ from the line it repeats, by grid column.
                          const changed = new Map<string, DupField>(
                            (dup?.fields ?? []).flatMap((f) => (DIFF_COLUMNS[f.field] ?? [f.field]).map((col) => [col, f] as const)));
                          // Dated outside the period (Third Party GDS): saved, but marked
                          // red so it is looked at first — the date cell itself says why.
                          const outside = skipped || leftOut ? undefined : outsideRows.get(r.__index__);
                          const dupNote = dup
                            ? `${DUP_LABEL[dup.kind]} — ${dup.kind === "in_file" ? "same ticket as" : "saved in"} ${twinText(dup, twin)}`
                              + (dup.fields.length ? `: ${changesText(dup.fields)}` : "")
                              + (leftOut ? ". Not saved — tick to save it." : ". Will be saved, flagged — untick to leave it out.")
                            : null;
                          return (
                            <tr key={r.__index__}
                                className={`border-b border-slate-100 ${
                                  skipped || leftOut ? "bg-slate-50/80 opacity-60"
                                    : outside ? "bg-rose-50/40 hover:bg-rose-50/70" : "hover:bg-slate-50/60"}`}
                                title={skipped ? "Not imported — see the note above."
                                  : dupNote ? dupNote
                                  : outside ? `Dated outside the statement period (${outsidePeriod?.period_label}) — check it before saving.`
                                  : undefined}>
                              <td className="px-2 py-1 text-slate-400 tabular-nums whitespace-nowrap">
                                <span className="inline-flex items-center gap-1">
                                  {dup && (
                                    <input type="checkbox" checked={!leftOut}
                                      onChange={() => toggleRow(r.__index__, dup.kind)}
                                      aria-label={`Save row ${r.__index__ + 1}`}
                                      className="h-3 w-3 cursor-pointer accent-blue-600" />
                                  )}
                                  {r.__index__ + 1}
                                </span>
                                {skipped && <span className="ml-1 text-[9px] uppercase tracking-wide text-slate-400">skip</span>}
                                {dup && (
                                  <span className={`ml-1 rounded px-1 py-px text-[9px] font-semibold uppercase tracking-wide ${DUP_TONE[dup.kind].tag}`}>
                                    {dup.kind === "exact" ? `Saved in ${twin?.period_label ?? "earlier"}`
                                      : dup.kind === "partial" ? `Partial · ${dup.fields.length} change${dup.fields.length === 1 ? "" : "s"}`
                                      : `Repeat of row ${dup.of_index != null ? dup.of_index + 1 : "?"}`}
                                  </span>
                                )}
                                {outside && (
                                  <span className="ml-1 rounded bg-rose-100 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-rose-700">
                                    Outside period
                                  </span>
                                )}
                              </td>
                              {reviewCols.map((c) => {
                                const src = columnMap[c.field];
                                const original = (src ? r[src] : null) ?? "";
                                const edited = isEdited(r, c.field);
                                // Violet = the AI read this out of the narration; amber = a
                                // person typed it. Both are edits and both save identically;
                                // the colour only says who to ask about a wrong value.
                                const fromAi = isAiFilled(r, c.field);
                                // This cell is the Booked/Issue Date that put the row outside.
                                const side = outside?.[c.field as PeriodDateField];
                                const sideNote = side
                                  ? `${DATE_LABEL[c.field as PeriodDateField]} is ${SIDE_TEXT[side]} (${outsidePeriod?.period_label})`
                                  : null;
                                // Put back in the sheet's order: Excel had day and month swapped.
                                const fixed = src && !edited ? fixedCells.get(`${r.__index__}|${src}`) : undefined;
                                const fixNote = fixed
                                  ? `Excel stored ${formatDay(fixed.stored)} — read as ${orderLabel(dateFormats[c.field])}: ${formatDay(fixed.read)}`
                                  : null;
                                // Not read: a date not in its column's format, or any value that
                                // doesn't fit its field (text in an amount) — it saves empty.
                                const badDate = unreadableDates.get(`${r.__index__}|${c.field}`);
                                const unread = !!badDate || !!unparsedRows.get(r.__index__)?.includes(c.field);
                                const badNote = badDate
                                  ? `Not a date in ${orderLabel(badDate.format ?? undefined)} — correct it, or change the format above`
                                  : unread ? "Couldn't be read as this field — it saves empty unless you correct it" : null;
                                // Differs from the line this row repeats (partial / repeated in file).
                                const diff = dup ? changed.get(c.field) : undefined;
                                const diffNote = diff && dup
                                  ? `${dup.kind === "in_file" ? `Row ${(dup.of_index ?? 0) + 1}` : `Saved in ${twin ? earlierName(twin) : "an earlier upload"}`}: ${fmtDupValue(diff, diff.saved)}`
                                  : null;
                                return (
                                  <td key={c.field} className="px-1 py-1">
                                    <input
                                      value={valueAt(r, c.field)}
                                      onChange={(e) => setCell(r.__index__, c.field, e.target.value, original)}
                                      title={[
                                        sideNote,
                                        badNote,
                                        diffNote,
                                        fixNote,
                                        fromAi ? `Read from the ${aiCfg?.label} — check it`
                                          : edited ? `Was: ${original || "(empty)"}` : null,
                                      ].filter(Boolean).join(" · ") || undefined}
                                      className={`w-full min-w-[90px] px-1.5 py-1 rounded border bg-transparent focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                                        fromAi
                                          ? "border-violet-300 bg-violet-50 text-violet-900 font-medium"
                                          : edited
                                          ? "border-amber-300 bg-amber-50 text-amber-900 font-medium"
                                          : side
                                          ? "border-rose-300 bg-rose-50 text-rose-800 font-medium"
                                          : unread
                                          ? "border-orange-300 bg-orange-50 text-orange-900 font-medium"
                                          : diff && dup
                                          ? DUP_TONE[dup.kind].cell
                                          : fixed
                                          ? "border-sky-200 bg-sky-50 text-sky-900"
                                          : "border-transparent text-slate-700 hover:border-slate-200"}${
                                        (side || unread) && (fromAi || edited) ? " ring-1 ring-rose-300" : ""}`}
                                    />
                                  </td>
                                );
                              })}
                            </tr>
                          );
                          })}
                        </tbody>
                      </table>
                    </div>
                    {pageCount > 1 && (
                      <div className="flex items-center justify-between px-3 py-2 border-t border-slate-100 bg-slate-50/60">
                        <button disabled={curPage === 0} onClick={() => setPage(curPage - 1)}
                          className="px-2 py-1 text-xs border border-slate-200 rounded-md bg-white hover:bg-slate-50 disabled:opacity-40">
                          Previous
                        </button>
                        <span className="text-[11px] text-slate-400">
                          {gridFilter !== "all" ? FILTER_LABEL[gridFilter] : "Rows"}{" "}
                          {curPage * PAGE + 1}–{Math.min((curPage + 1) * PAGE, shownRows.length)}
                          {gridFilter !== "all" && <> of {shownRows.length}</>}
                        </span>
                        <button disabled={curPage + 1 >= pageCount} onClick={() => setPage(curPage + 1)}
                          className="px-2 py-1 text-xs border border-slate-200 rounded-md bg-white hover:bg-slate-50 disabled:opacity-40">
                          Next
                        </button>
                      </div>
                    )}
                  </div>
                </>
              )}
            </>
          )}

          {/* ── 4. Done ───────────────────────────────────────────────────── */}
          {step === "done" && saved && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="w-14 h-14 rounded-full bg-emerald-50 flex items-center justify-center mb-4">
                <PartyPopper className="w-7 h-7 text-emerald-600" />
              </div>
              <p className="text-sm font-semibold text-slate-800">
                Imported {saved.inserted.toLocaleString("en-IN")} row{saved.inserted === 1 ? "" : "s"}.
              </p>
              {/* The file had more lines than this. Say so here, where the reason is still
                  at hand — the uploads list shows only the entry count. */}
              {saved.excluded_rows > 0 && rowFilter && (
                <p className="text-xs text-slate-600 mt-1.5 max-w-md">
                  {saved.excluded_rows.toLocaleString("en-IN")} {rowFilter.label}
                  {" "}({rowFilter.exclude.join(", ")}) {saved.excluded_rows === 1 ? "was" : "were"} skipped
                  — no money moved on them, so there is nothing to reconcile.
                </p>
              )}
              {saved.period_from && saved.period_to && (
                <p className="text-xs text-slate-600 mt-1">
                  Statement period <strong>{formatPeriod(saved.period_from, saved.period_to)}</strong>.
                </p>
              )}
              {saved.date_formats && dateFields.length > 0 && (
                <p className="text-xs text-slate-600 mt-1">
                  Dates read as{" "}
                  {dateFields.map((f, i) => (
                    <span key={f.field}>
                      {i > 0 && " · "}{f.header} <strong>{orderLabel(saved.date_formats?.[f.field])}</strong>
                    </span>
                  ))}.
                </p>
              )}
              {!!saved.outside_period && (
                <p className="text-xs text-rose-700 mt-1">
                  {saved.outside_period.toLocaleString("en-IN")} ticket{saved.outside_period === 1 ? "" : "s"} dated
                  outside it {saved.outside_period === 1 ? "was" : "were"} saved as you reviewed {saved.outside_period === 1 ? "it" : "them"}.
                </p>
              )}
              {saved.controls && <ControlsSummary controls={saved.controls} balanceRows={saved.balance_rows ?? 0} />}
              {saved.duplicates && <DuplicatesSummary report={saved.duplicates} />}
              <p className="text-xs text-slate-500 mt-1">
                {saved.edited_rows > 0
                  ? `${saved.edited_rows} row${saved.edited_rows === 1 ? " was" : "s were"} saved with your corrections. `
                  : ""}
                {doneHint}
              </p>
            </div>
          )}
        </div>

        {/* ── footer ─────────────────────────────────────────────────────── */}
        {/* On a page it stays in view below a long review grid. */}
        <div className={`flex items-center justify-between gap-2 px-5 border-t border-slate-100${
          asPage ? " py-3 sticky bottom-0 z-10 bg-white rounded-b-xl" : " py-3.5"}`}>
          <div className="text-[11px] text-slate-400">
            {extracted && step !== "done" && (
              <>{extracted.file_name} · {extracted.total_rows.toLocaleString("en-IN")} rows
                {capturesPeriod && periodFrom && periodTo && <> · Period {formatPeriod(periodFrom, periodTo)}</>}
                {dateFields.length > 0 && formatsComplete && (
                  <> · Dates {dateFields.map((f) => orderLabel(dateFormats[f.field])).join(" / ")}</>
                )}</>
            )}
          </div>
          <div className="flex items-center gap-2">
            {step === "upload" && (
              <>
                <button onClick={leave}
                  className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
                  Cancel
                </button>
                <button onClick={startExtract} disabled={!file || busy || checkingPeriod}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
                  {busy || checkingPeriod ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />}
                  {checkingPeriod ? "Checking period…" : busy ? "Reading…" : "Next: map columns"}
                </button>
              </>
            )}
            {step === "mapping" && (
              <>
                <button onClick={() => setStep("upload")}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
                  <ArrowLeft className="w-3.5 h-3.5" /> Back
                </button>
                <button onClick={() => { if (checkMapping()) { setPage(0); setStep("review"); } }}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
                  <ArrowRight className="w-3.5 h-3.5" /> Next: review
                </button>
              </>
            )}
            {step === "review" && (
              <>
                <button onClick={() => setStep("mapping")}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
                  <ArrowLeft className="w-3.5 h-3.5" /> Back to mapping
                </button>
                {/* Held while the check runs, so "Before you save" below is asked about the
                    file as it now stands, not as it was before the last edit. */}
                <button onClick={() => (needsConfirm ? setConfirmSave(true) : void doConfirm())}
                  disabled={saving || (capturesPeriod && previewBusy) || nothingToSave}
                  title={nothingToSave ? "Every entry is left out as a duplicate — there is nothing to save." : undefined}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed">
                  {saving || (capturesPeriod && previewBusy)
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  {saving ? "Saving…" : capturesPeriod && previewBusy ? "Checking…" : "Confirm & save"}
                </button>
              </>
            )}
            {step === "done" && (
              <button onClick={onDone}
                className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
                Done
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Page layout: leaving mid-mapping or mid-review — nothing is saved yet. */}
      {confirmLeave && (
        <ConfirmDialog
          title="Leave this upload?"
          confirmLabel="Leave"
          onConfirm={async () => { setConfirmLeave(false); onClose(); }}
          onClose={() => setConfirmLeave(false)}
        >
          <p>
            Nothing has been saved yet. The column mapping
            {editedRowCount > 0 && <> and the {editedRowCount} row{editedRowCount === 1 ? "" : "s"} you corrected</>}{" "}
            will be lost.
          </p>
        </ConfirmDialog>
      )}

      {/* Asked BEFORE the file is read: this agency already has this period (or part of it) —
          often the same statement sent again. Continue reads it; the review step shows which
          rows are already saved, which changed and which are new, and the user chooses. */}
      {earlier && earlier.length > 0 && (
        <ConfirmDialog
          title={earlier.some((e) => (e.period_from ?? "") <= periodFrom && (e.period_to ?? "") >= periodTo)
            ? `${formatPeriod(periodFrom, periodTo)} is already uploaded`
            : `Part of ${formatPeriod(periodFrom, periodTo)} is already uploaded`}
          confirmLabel="Continue"
          danger={false}
          onConfirm={async () => { setEarlier(null); void doExtract(); }}
          onClose={() => setEarlier(null)}
        >
          <p>
            {agency?.name ?? "This agency"} already has {earlier.length === 1 ? "an upload" : `${earlier.length} uploads`} covering
            {" "}{earlier.length === 1 ? "this period" : "these days"}:
          </p>
          <ul className="space-y-1.5">
            {earlier.map((e) => (
              <li key={e.batch_id} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                <span className="font-semibold text-gray-800">{e.period_label}</span>
                <span className="text-gray-500"> · {e.source_file ?? "—"}</span>
                <span className="block text-[11px] text-gray-500 mt-0.5">
                  Uploaded {formatUploadedAt(e.uploaded_at)} · {e.new_entries.toLocaleString("en-IN")}{" "}
                  {e.new_entries === 1 ? "entry" : "entries"} saved
                </span>
              </li>
            ))}
          </ul>
          <p>
            <strong>Continue</strong> to read this file. Every entry is checked against this agency&apos;s saved
            statements: the review step shows which are already uploaded (not saved again unless you choose),
            which are the same ticket with something changed, and which are new — saved as a new upload with its
            own date and time.
          </p>
          <p><strong>Cancel</strong> to change the period or the file.</p>
        </ConfirmDialog>
      )}

      {/* Asked at Save when the file holds duplicates or tickets dated outside the period:
          what Save is about to do with each, in one place — the user saying they have looked. */}
      {confirmSave && savePreview && entriesToSave != null && (() => {
        const n = (v: number) => v.toLocaleString("en-IN");
        const outsideLines = (outsidePeriod?.lines ?? []).filter((l) => l.index == null || willSave(l.index));
        const outsideCount = outsideSaved.length;
        return (
          <ConfirmDialog
            title="Before you save"
            confirmLabel="Confirm & save"
            danger={false}
            onConfirm={async () => { setConfirmSave(false); void doConfirm(); }}
            onClose={() => setConfirmSave(false)}
          >
            <p>
              Save <strong>{n(entriesToSave)} {entriesToSave === 1 ? "entry" : "entries"}</strong>
              {savePreview.balance_lines > 0 && <> (+ {savePreview.balance_lines} balance line{savePreview.balance_lines === 1 ? "" : "s"})</>}{" "}
              as a new statement for {periodText}:
            </p>
            <ul className="space-y-1">
              <li className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5">
                <strong>{n(savePreview.counts.new)}</strong> new — saved
              </li>
              {DUP_KINDS.filter((k) => savePreview.counts[k] > 0).map((k) => {
                const total = savePreview.counts[k], s = dupTally.saved[k];
                return (
                  <li key={k} className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5">
                    <span className={`rounded px-1 py-px text-[10px] font-semibold uppercase tracking-wide ${DUP_TONE[k].tag}`}>
                      {DUP_LABEL[k]}
                    </span>{" "}
                    <strong>{n(total)}</strong> —{" "}
                    {s === total ? (k === "exact" ? "saved again, flagged" : "saved, flagged")
                      : s === 0 ? "not saved"
                      : `${n(s)} saved, flagged · ${n(total - s)} not saved`}
                  </li>
                );
              })}
              {outsideCount > 0 && (
                <li className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-rose-800">
                  <strong>{n(outsideCount)}</strong> dated outside {outsidePeriod?.period_label} — saved as{" "}
                  {outsideCount === 1 ? "it stands" : "they stand"}
                  <span className="block text-[11px] mt-0.5">
                    {outsideLines.slice(0, 3).map((l) => `${l.ticket_number ?? "—"} (${
                      (Object.entries(l.outside) as [PeriodDateField, OutsideSide][])
                        .map(([f, s]) => `${DATE_LABEL[f]} ${s === "unreadable" ? "unreadable" : `${formatDay(l[f])}, ${s}`}`)
                        .join(" · ")})`).join("; ")}
                    {outsideCount > 3 ? `; …and ${n(outsideCount - 3)} more` : ""}
                  </span>
                </li>
              )}
            </ul>
            <p>
              <strong>Confirm &amp; save</strong> to save as listed. <strong>Cancel</strong> to keep reviewing — change
              what is saved above or row by row, correct a cell, or go back and change the period.
            </p>
          </ConfirmDialog>
        );
      })()}
    </div>
  );
}
