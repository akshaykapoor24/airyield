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
// Modelled on components/statements/lcc/LccUploadWizard.tsx, which does the same job for
// LCC Detailed. The two are not shared because that one ingests asynchronously behind a
// progress poller and has no per-cell editing — the mapping screens look alike, the rest
// of the flow does not.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  X, Upload, FileSpreadsheet, CheckCircle2, Loader2, Search, AlertTriangle,
  ArrowLeft, ArrowRight, Wand2, Eraser, PartyPopper, Pencil, RotateCcw, Filter,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import { notifyRequired } from "@/lib/requiredFields";
import LccPartyPicker, { type PartyOption } from "@/components/statements/lcc/LccPartyPicker";

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
};

type SaveResp = {
  inserted: number;
  edited_rows: number;
  /** Rows dropped by `row_filter` — 0 for the types that drop nothing. */
  excluded_rows: number;
  /** Null unless the type has a row filter; false means its column was never mapped, so
   *  nothing was classified and nothing was skipped. */
  filter_column_mapped: boolean | null;
};

/** One row of GET /suppliers/ — the platform-admin master. `code` is the unique one:
 *  141 of its 2,340 names repeat across branches. */
type SupplierOpt = {
  id: number; name: string;
  code?: string | null; branch?: string | null; city?: string | null;
};

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

function StepBar({ step }: { step: Step }) {
  const steps: { key: Step; label: string }[] = [
    { key: "upload", label: "Upload" },
    { key: "mapping", label: "Map columns" },
    { key: "review", label: "Review & edit" },
    { key: "done", label: "Save" },
  ];
  const order: Step[] = ["upload", "mapping", "review", "done"];
  const activeIdx = order.indexOf(step);
  return (
    <div className="flex items-center gap-2 px-5 py-3 border-b border-slate-100 bg-slate-50/60">
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

export default function StatementUploadWizard({
  apiBase, title, requireSupplier = false, doneHint, onClose, onDone,
}: {
  apiBase: string;
  title: string;
  /** Third-party types only — the uploader must name the consolidator from the platform-admin
   *  Supplier master, because the file never says who sent it and the B2B deal is matched
   *  against the answer. Off for NDC: an airline's own export names its carrier, so there is
   *  nothing for the uploader to declare and asking would be a question with no purpose. */
  requireSupplier?: boolean;
  /** One line on the success screen telling the user where the rows went. */
  doneHint?: string;
  onClose: () => void;
  onDone: () => void;
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
  const [suppliers, setSuppliers] = useState<SupplierOpt[]>([]);
  const [supplierId, setSupplierId] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Mapping
  const [search, setSearch] = useState("");

  // Review — sparse, keyed by the row's position in the file. Only what the user actually
  // changed is sent, so a 900-row statement carries three edits, not 900 rows of payload.
  const [edits, setEdits] = useState<Record<number, Record<string, string>>>({});
  const [page, setPage] = useState(0);

  useEffect(() => {
    api.get<StdResp>(`${apiBase}/standard-columns`)
      .then((r) => setStd(r.data))
      .catch(() => toast.error("Failed to load the column list."));
  }, [apiBase]);

  // The platform-admin Supplier master — the same list a B2B deal picks its supplier
  // from, which is what lets the two sides of the match name the same thing. Only fetched
  // for the types that ask for it; the others would be making a call they never read.
  useEffect(() => {
    if (!requireSupplier) return;
    api.get<SupplierOpt[]>("/suppliers/", { params: { limit: 5000 } })
      .then((r) => setSuppliers(r.data))
      .catch(() => toast.error("Failed to load the Supplier master."));
  }, [requireSupplier]);

  // Label = name, sublabel = branch/city · code. 141 of the master's names repeat across
  // branches ("Riya Travel & Tours" is fourteen rows), so a label stopping at the name
  // would render identical options and the pick would be a coin toss. `code` is unique.
  const supplierOptions: PartyOption<"agency">[] = useMemo(
    () => suppliers.map((s) => ({
      value: s.id,
      label: s.name,
      sublabel: [s.branch || s.city, s.code].filter(Boolean).join(" · "),
      kind: "agency" as const,
    })),
    [suppliers],
  );

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

  const doExtract = async () => {
    if (!file) { notifyRequired("Choose a statement file to continue."); return; }
    if (requireSupplier && supplierId == null) {
      notifyRequired("Select the agency this statement came from — the file itself doesn't name your consolidator.");
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (supplierId != null) fd.append("supplier_id", String(supplierId));
      const { data } = await api.post<ExtractResp>(`${apiBase}/extract`, fd);
      setExtracted(data);
      setColumnMap(data.suggested_mapping || {});
      setEdits({});
      setPage(0);
      setStep("mapping");
    } catch (e) { toast.error(errMsg(e, "Could not read the file.")); }
    finally { setBusy(false); }
  };

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
  // Only the fields that are actually mapped are worth showing: a column nobody mapped
  // has nothing to review.
  const reviewCols = useMemo(
    () => allCols.filter((c) => columnMap[c.field]), [allCols, columnMap]);

  const valueAt = (r: SampleRow, field: string): string => {
    const edit = edits[r.__index__]?.[field];
    if (edit !== undefined) return edit;
    const src = columnMap[field];
    return (src ? r[src] : null) ?? "";
  };
  const isEdited = (r: SampleRow, field: string) => edits[r.__index__]?.[field] !== undefined;

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
  };

  const editedRowCount = Object.keys(edits).length;
  const rows = extracted?.sample_rows ?? [];
  const pageRows = rows.slice(page * PAGE, page * PAGE + PAGE);
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE));

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
      fd.append("header_row", String(extracted.header_row));
      fd.append("file_digest", extracted.file_digest);
      fd.append("edits", JSON.stringify(edits));
      const { data } = await api.post<SaveResp>(`${apiBase}/confirm`, fd);
      setSaved(data);
      setStep("done");
    } catch (e) { toast.error(errMsg(e, "Could not save the statement.")); }
    finally { setSaving(false); }
  };

  // ── render ────────────────────────────────────────────────────────────────
  const truncated = !!extracted && extracted.total_rows > extracted.preview_rows;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-5xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-800">Upload {title} statement</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        <StepBar step={step} />

        <div className="flex-1 overflow-y-auto p-5">
          {/* ── 1. Upload ─────────────────────────────────────────────────── */}
          {step === "upload" && (
            <>
              {/* Agency FIRST: it decides which B2B deal prices the statement, and a
                  wrong pick is not visible anywhere later. Labelled "Agency" because that
                  is what the trade calls it; the values are rows in the platform-admin
                  Supplier master. */}
              {requireSupplier && (
              <div className="rounded-lg border border-slate-200 bg-slate-50/60 px-3.5 py-3 mb-4">
                <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                  Agency <span className="text-red-500">*</span>
                </label>
                <LccPartyPicker
                  options={supplierOptions}
                  value={supplierId}
                  onChange={(o) => setSupplierId(o?.value ?? null)}
                  disabled={suppliers.length === 0}
                  placeholder={suppliers.length ? "Select the consolidator who sent this…" : "Supplier master is empty"}
                  searchPlaceholder="Search the Supplier master…"
                  emptyLabel="No suppliers yet — ask your platform admin to add them."
                />
                <p className="text-[11px] text-slate-400 mt-1.5">
                  Who sent you this statement. The file doesn&apos;t say, and Commission income
                  needs it to find the right B2B deal. Names come from the Supplier master, the
                  same list a B2B deal picks its supplier from — pick the right branch, since
                  each one is its own contract.
                </p>
                {suppliers.length === 0 && (
                  <p className="text-[11px] text-amber-600 mt-2">
                    The Supplier master is empty. Ask your platform admin to add the
                    consolidator before uploading.
                  </p>
                )}
              </div>
              )}

              <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0] ?? null); }}
                onClick={() => !file && inputRef.current?.click()}
                className={`cursor-pointer flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center ${
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

              <p className="text-[11px] text-slate-400 mt-3">
                Any layout works — you will map the columns on the next step. Press
                <strong> Template</strong> on the previous screen for a sheet that maps itself.
              </p>
            </>
          )}

          {/* ── 2. Map columns ────────────────────────────────────────────── */}
          {step === "mapping" && extracted && (
            <>
              <div className={`flex items-start gap-2 px-3 py-2.5 mb-3 rounded-xl border text-xs ${
                extracted.is_template_match
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                  : "border-sky-200 bg-sky-50 text-sky-800"}`}>
                {extracted.is_template_match
                  ? <CheckCircle2 className="w-4 h-4 shrink-0 mt-px" />
                  : <Wand2 className="w-4 h-4 shrink-0 mt-px" />}
                <span>
                  {extracted.is_template_match ? (
                    <><strong>This file matches the template.</strong> All {extracted.matched_columns} columns
                      were recognised — check them if you like, then continue.</>
                  ) : (
                    <><strong>{extracted.matched_columns} of {extracted.columns.length} columns
                      were recognised by name.</strong> Set the rest below: pick, for each field,
                      which of your columns holds it. Anything left as
                      <em> not in file</em> is simply not imported.</>
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
              <div className="flex items-start gap-2 px-3 py-2.5 mb-3 rounded-xl border border-slate-200 bg-slate-50 text-xs text-slate-600">
                <Pencil className="w-4 h-4 shrink-0 mt-px text-slate-400" />
                <span>
                  This is the file as your mapping reads it. <strong>Click any cell to correct
                  it</strong> — dates and amounts are still normalised after you edit, so
                  typing <em>13-08-2026</em> or <em>1,23,456.78</em> is fine.
                  {truncated && (
                    <> Only the first {extracted.preview_rows.toLocaleString("en-IN")} of{" "}
                      {extracted.total_rows.toLocaleString("en-IN")} rows are shown and
                      editable; the rest import exactly as mapped.</>
                  )}
                </span>
              </div>

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
                  <div className="flex items-center gap-2 mb-2 text-[11px] text-slate-400">
                    <span>
                      {rows.length.toLocaleString("en-IN")} row{rows.length === 1 ? "" : "s"} ·{" "}
                      {reviewCols.length} mapped column{reviewCols.length === 1 ? "" : "s"}
                    </span>
                    {editedRowCount > 0 && (
                      <span className="inline-flex items-center gap-1 text-amber-700 font-semibold">
                        <Pencil className="w-3 h-3" /> {editedRowCount} row{editedRowCount === 1 ? "" : "s"} edited
                        <button onClick={() => setEdits({})}
                          className="ml-1 inline-flex items-center gap-1 text-slate-400 hover:text-slate-700 font-medium">
                          <RotateCcw className="w-3 h-3" /> undo all
                        </button>
                      </span>
                    )}
                    <span className="ml-auto">Page {page + 1} of {pageCount}</span>
                  </div>

                  <div className="border border-slate-200 rounded-xl overflow-hidden">
                    <div className="overflow-x-auto max-h-[46vh]">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0">
                          <tr className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400 whitespace-nowrap">
                            <th className="text-left px-2 py-2 font-semibold w-10">#</th>
                            {reviewCols.map((c) => (
                              <th key={c.field} className="text-left px-2 py-2 font-semibold"
                                  title={`${c.field} ← ${columnMap[c.field]}`}>
                                {c.header}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {pageRows.map((r) => {
                          // Still editable, deliberately: the way out of the grey is to fix
                          // the TXN Type cell, and a disabled input would make the row look
                          // like a dead end.
                          const skipped = isSkipped(r);
                          return (
                            <tr key={r.__index__}
                                className={`border-b border-slate-100 ${
                                  skipped ? "bg-slate-50/80 opacity-60" : "hover:bg-slate-50/60"}`}
                                title={skipped ? "Not imported — see the note above." : undefined}>
                              <td className="px-2 py-1 text-slate-400 tabular-nums whitespace-nowrap">
                                {r.__index__ + 1}
                                {skipped && <span className="ml-1 text-[9px] uppercase tracking-wide text-slate-400">skip</span>}
                              </td>
                              {reviewCols.map((c) => {
                                const src = columnMap[c.field];
                                const original = (src ? r[src] : null) ?? "";
                                const edited = isEdited(r, c.field);
                                return (
                                  <td key={c.field} className="px-1 py-1">
                                    <input
                                      value={valueAt(r, c.field)}
                                      onChange={(e) => setCell(r.__index__, c.field, e.target.value, original)}
                                      title={edited ? `Was: ${original || "(empty)"}` : undefined}
                                      className={`w-full min-w-[90px] px-1.5 py-1 rounded border bg-transparent focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                                        edited
                                          ? "border-amber-300 bg-amber-50 text-amber-900 font-medium"
                                          : "border-transparent text-slate-700 hover:border-slate-200"}`}
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
                        <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}
                          className="px-2 py-1 text-xs border border-slate-200 rounded-md bg-white hover:bg-slate-50 disabled:opacity-40">
                          Previous
                        </button>
                        <span className="text-[11px] text-slate-400">
                          Rows {page * PAGE + 1}–{Math.min((page + 1) * PAGE, rows.length)}
                        </span>
                        <button disabled={page + 1 >= pageCount} onClick={() => setPage((p) => p + 1)}
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
        <div className="flex items-center justify-between gap-2 px-5 py-3.5 border-t border-slate-100">
          <div className="text-[11px] text-slate-400">
            {extracted && step !== "done" && (
              <>{extracted.file_name} · {extracted.total_rows.toLocaleString("en-IN")} rows</>
            )}
          </div>
          <div className="flex items-center gap-2">
            {step === "upload" && (
              <>
                <button onClick={onClose}
                  className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
                  Cancel
                </button>
                <button onClick={doExtract} disabled={!file || busy}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
                  {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />}
                  {busy ? "Reading…" : "Next: map columns"}
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
                <button onClick={doConfirm} disabled={saving}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  {saving ? "Saving…" : "Confirm & save"}
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
    </div>
  );
}
