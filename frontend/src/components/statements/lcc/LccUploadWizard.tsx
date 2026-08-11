"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  X, Upload, FileSpreadsheet, CheckCircle2, Loader2, Search, ChevronDown, ChevronRight,
  AlertTriangle, ArrowLeft, ArrowRight, Wand2, Eraser, PartyPopper,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import { notifyRequired } from "@/lib/requiredFields";

type Step = "upload" | "mapping" | "preview" | "progress" | "done";

type StdCol = { header: string; field: string; role: "core" | "tax" | "leg"; dtype: string; leg_no?: number; slot?: string };
type StdGroup = { group: string; columns: StdCol[] };
type SampleRow = Record<string, string | null>;

type ExtractResp = {
  batch_id: string;
  file_name: string;
  total_rows: number;
  header_row: number;
  source_format: string;
  xls_columns: string[];
  suggested_mapping: Record<string, string>;   // {field: xls_column}
  sample_rows: SampleRow[];
  is_template_match: boolean;
  matched_columns: number;
  standard_total: number;
};

type StatusResp = {
  batch_id: string; status: string; total_rows: number; processed_rows: number;
  expected_rows: number | null; progress_pct: number; error: string | null;
};

const SKIP = "";   // "— not in file —"

/**
 * Mapping rules.
 *
 * Only ONE of each group has to be mapped — airlines label these differently and
 * not every export carries all of them.
 *
 * IDENTIFIER is hard-required. Ticket Search finds an LCC Detailed row by
 * `record_locator` or `gds_record_locator` and nothing else
 * (api/v1/ticket_details.py, the lcc-detailed `match` list). Ingest a batch with
 * neither mapped and every row is permanently unreachable from the product —
 * the import reports "50,000 rows saved" and the rows may as well not exist.
 *
 * AMOUNT is hard-required too: a settlement statement row with no money on it
 * cannot be reconciled against anything, so it is a mis-mapping, not a choice.
 *
 * DATE is a warning only — some exports genuinely carry the period in the file
 * name rather than per row.
 */
const REQUIRED_MAPPING_GROUPS: { label: string; fields: string[]; headers: string }[] = [
  { label: "a booking identifier", fields: ["record_locator", "gds_record_locator"], headers: "RecordLocator or GDS_recordlocator" },
  { label: "an amount",            fields: ["total", "base_fare"],                   headers: "Total or BaseFare" },
];
const DATE_FIELDS = ["transaction_date", "booking_date", "payment_datetime"];

function errMsg(e: unknown, fallback: string): string {
  const m = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return typeof m === "string" ? m : fallback;
}

/** Client-side numeric parse mirroring the backend `_to_decimal`. */
function num(v: string | null | undefined): number | null {
  if (v == null) return null;
  const s = String(v).replace(/[^\d.\-]/g, "");
  if (!s || s === "-" || s === "." || s === "-.") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function StepBar({ step }: { step: Step }) {
  const steps: { key: Step; label: string }[] = [
    { key: "upload", label: "Upload" },
    { key: "mapping", label: "Map columns" },
    { key: "preview", label: "Preview" },
    { key: "progress", label: "Save" },
  ];
  const order = ["upload", "mapping", "preview", "progress", "done"];
  const activeIdx = order.indexOf(step === "done" ? "progress" : step);
  return (
    <div className="flex items-center gap-2 px-5 py-3 border-b border-slate-100 bg-slate-50/60">
      {steps.map((s, i) => {
        const done = order.indexOf(s.key) < activeIdx;
        const active = s.key === step || (step === "done" && s.key === "progress");
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

export default function LccUploadWizard({
  apiBase, title, onClose, onDone,
}: { apiBase: string; title: string; onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState<Step>("upload");
  const [groups, setGroups] = useState<StdGroup[]>([]);
  const [extracted, setExtracted] = useState<ExtractResp | null>(null);
  const [columnMap, setColumnMap] = useState<Record<string, string>>({});

  // Upload state
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [expectedRows, setExpectedRows] = useState("");   // user-declared record count (optional)
  const inputRef = useRef<HTMLInputElement>(null);
  const expectedNum = (() => { const n = parseInt(expectedRows.replace(/[^\d]/g, ""), 10); return Number.isFinite(n) && n > 0 ? n : null; })();

  // Mapping state
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ "Taxes & Fees": true });

  // Progress state
  const [statusData, setStatusData] = useState<StatusResp | null>(null);

  // Load the standard column spec once.
  useEffect(() => {
    api.get<{ groups: StdGroup[] }>(`${apiBase}/standard-columns`)
      .then((r) => setGroups(r.data.groups))
      .catch(() => toast.error("Failed to load column definitions."));
  }, [apiBase]);

  const allCols: StdCol[] = useMemo(() => groups.flatMap((g) => g.columns), [groups]);
  const totalStd = allCols.length || extracted?.standard_total || 0;
  const mappedCount = Object.values(columnMap).filter(Boolean).length;
  // 87 of the 129 standard columns are tax codes, so "something is mapped" was
  // satisfied by a single tax column. Count the ones that carry the row's identity.
  const coreMappedCount = allCols.filter((c) => c.role === "core" && columnMap[c.field]).length;

  const missingRequiredGroups = REQUIRED_MAPPING_GROUPS
    .filter((g) => !g.fields.some((f) => columnMap[f]))
    .map((g) => `${g.label} (${g.headers})`);
  const dateMissing = !DATE_FIELDS.some((f) => columnMap[f]);

  /** Guard for both Preview and Confirm — the mapping is what makes the rows usable. */
  const checkMapping = (): boolean => {
    if (coreMappedCount === 0) {
      return notifyRequired("Map at least one Core column — mapping only taxes or legs would import rows with no ticket data on them.");
    }
    if (missingRequiredGroups.length) {
      return notifyRequired(
        missingRequiredGroups.length === 1
          ? `Map ${missingRequiredGroups[0]} before continuing.`
          : `Map ${missingRequiredGroups.join(" and ")} before continuing.`
      );
    }
    return true;
  };

  // ── Upload ─────────────────────────────────────────────────────────────────
  const pickFile = (f: File | null) => {
    if (f && !/\.(xlsx|xls|csv)$/i.test(f.name)) { toast.error("Choose an .xlsx, .xls or .csv file."); return; }
    setFile(f);
  };

  const doExtract = async () => {
    if (!file) { notifyRequired("Choose a statement file (.xlsx, .xls or .csv) to continue."); return; }
    setUploading(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const { data } = await api.post<ExtractResp>(`${apiBase}/extract`, fd);
      setExtracted(data);
      setColumnMap(data.suggested_mapping || {});
      setStep("mapping");
    } catch (e) { toast.error(errMsg(e, "Could not read the file.")); }
    finally { setUploading(false); }
  };

  // ── Mapping ──────────────────────────────────────────────────────────────
  const setMap = (field: string, xlsCol: string) =>
    setColumnMap((p) => { const n = { ...p }; if (xlsCol) n[field] = xlsCol; else delete n[field]; return n; });
  const autoMapAll = () => setColumnMap(extracted?.suggested_mapping || {});
  const clearAll = () => setColumnMap({});

  const filteredGroups: StdGroup[] = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({ ...g, columns: g.columns.filter((c) => c.header.toLowerCase().includes(q) || c.field.toLowerCase().includes(q)) }))
      .filter((g) => g.columns.length > 0);
  }, [groups, search]);

  // ── Preview (folded client-side from sample rows + current mapping) ──────
  const previewRows = useMemo(() => {
    if (!extracted) return [];
    const coreCols = allCols.filter((c) => c.role === "core");
    const taxCols = allCols.filter((c) => c.role === "tax");
    const legCols = allCols.filter((c) => c.role === "leg");
    return extracted.sample_rows.slice(0, 50).map((sr) => {
      const core: Record<string, string> = {};
      for (const c of coreCols) {
        const src = columnMap[c.field];
        core[c.field] = src ? (sr[src] ?? "") : "";
      }
      const taxes: string[] = [];
      let taxesTotal = 0;
      for (const c of taxCols) {
        const src = columnMap[c.field];
        const n = src ? num(sr[src]) : null;
        if (n != null && n !== 0) { taxes.push(`${c.header} ${n}`); taxesTotal += n; }
      }
      const legMap: Record<number, { route?: string; flight?: string; dep?: string }> = {};
      for (const c of legCols) {
        const src = columnMap[c.field];
        const v = src ? (sr[src] ?? "") : "";
        if (!v || c.leg_no == null) continue;
        legMap[c.leg_no] = legMap[c.leg_no] || {};
        if (c.slot === "route") legMap[c.leg_no].route = v;
        else if (c.slot === "flight_no") legMap[c.leg_no].flight = v;
        else if (c.slot === "dep_date") legMap[c.leg_no].dep = v;
      }
      const segs = Object.keys(legMap).map(Number).sort((a, b) => a - b)
        .filter((n) => legMap[n].route || legMap[n].flight)
        .map((n) => `${legMap[n].route ?? ""} ${legMap[n].flight ?? ""}`.trim());
      return { core, taxes: taxes.join(" · "), taxesTotal: taxes.length ? String(taxesTotal) : "", segments: segs.join(" · ") };
    });
  }, [extracted, columnMap, allCols]);

  const coreColsForPreview = allCols.filter((c) => c.role === "core");

  // ── Confirm + progress polling ───────────────────────────────────────────
  const doConfirm = async () => {
    if (!extracted) { notifyRequired("Nothing to import — upload a file first."); return; }
    // Re-checked here, not just on the Preview button: this is the call that
    // actually writes rows, and the user can reach it after editing the mapping.
    if (!checkMapping()) { setStep("mapping"); return; }
    try {
      await api.post(`${apiBase}/confirm`, { batch_id: extracted.batch_id, column_map: columnMap, expected_rows: expectedNum });
      setStatusData({ batch_id: extracted.batch_id, status: "pending", total_rows: extracted.total_rows, processed_rows: 0, expected_rows: expectedNum, progress_pct: 0, error: null });
      setStep("progress");
    } catch (e) { toast.error(errMsg(e, "Could not start the import.")); }
  };

  const pollStatus = useCallback(async () => {
    if (!extracted) return;
    try {
      const { data } = await api.get<StatusResp>(`${apiBase}/status/${extracted.batch_id}`);
      setStatusData(data);
      if (data.status === "completed") setStep("done");
      else if (data.status === "failed") toast.error(data.error || "Import failed.");
    } catch { /* keep polling */ }
  }, [apiBase, extracted]);

  useEffect(() => {
    if (step !== "progress") return;
    const t = setInterval(pollStatus, 1500);
    pollStatus();
    return () => clearInterval(t);
  }, [step, pollStatus]);

  const failed = statusData?.status === "failed";

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-5xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-800">Upload {title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
        </div>

        <StepBar step={step} />

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* STEP 1 — UPLOAD */}
          {step === "upload" && (
            <div>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0] ?? null); }}
                onClick={() => !file && inputRef.current?.click()}
                className={`cursor-pointer flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 text-center ${
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
                    <p className="text-sm font-medium text-slate-700">Drop your statement export here</p>
                    <p className="text-xs text-slate-400 mt-0.5">or click to browse · .xlsx, .xls, .csv</p>
                  </>
                )}
                <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => pickFile(e.target.files?.[0] ?? null)} />
              </div>

              {/* Expected record count — a manual sanity check confirmed after import. */}
              <div className="mt-4 flex flex-wrap items-center gap-2.5 rounded-lg border border-slate-200 bg-slate-50/60 px-3.5 py-3">
                <label htmlFor="lcc-expected-rows" className="text-xs font-semibold text-slate-700">
                  Expected records <span className="font-normal text-slate-400">(optional)</span>
                </label>
                <input id="lcc-expected-rows" value={expectedRows} onChange={(e) => setExpectedRows(e.target.value)}
                  inputMode="numeric" placeholder="e.g. 50,000"
                  className="w-36 px-3 py-1.5 border border-slate-200 rounded-lg text-xs tabular-nums bg-white focus:outline-none focus:ring-1 focus:ring-blue-400" />
                <span className="text-[11px] text-slate-400">
                  How many records are in this file? We&apos;ll confirm that many rows landed in the database after import.
                </span>
              </div>

              <p className="text-[11px] text-slate-400 mt-3">Next you&apos;ll map the file&apos;s columns to the standard template, preview a sample, then save. The original file is stored.</p>
            </div>
          )}

          {/* STEP 2 — MAPPING */}
          {step === "mapping" && extracted && (
            <div>
              <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 mb-3 text-xs ${extracted.is_template_match ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                {extracted.is_template_match
                  ? <><CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /><span>Looks like the standard template — all {totalStd} columns auto-matched. Review and adjust if needed.</span></>
                  : <><AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /><span>{mappedCount} of {totalStd} columns auto-matched. Map the remaining columns below (or leave them unmapped).</span></>}
              </div>

              {/* What must be mapped, stated up front rather than only on rejection. */}
              {missingRequiredGroups.length > 0 && (
                <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 mb-3 text-xs text-red-700">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>
                    <b>Still required:</b> {missingRequiredGroups.join(", ")}.{" "}
                    Rows without a booking identifier can never be found in Ticket Search.
                  </span>
                </div>
              )}

              <div className="flex items-center gap-2 mb-3">
                <div className="relative flex-1 max-w-xs">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                  <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search standard columns…"
                    className="w-full pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-slate-50" />
                </div>
                <span className="text-[11px] text-slate-400">{mappedCount} / {totalStd} mapped</span>
                <div className="ml-auto flex items-center gap-2">
                  <button onClick={autoMapAll} className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-medium text-blue-700 border border-blue-200 bg-blue-50 rounded-lg hover:bg-blue-100"><Wand2 className="w-3.5 h-3.5" /> Auto-map</button>
                  <button onClick={clearAll} className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"><Eraser className="w-3.5 h-3.5" /> Clear</button>
                </div>
              </div>

              <div className="space-y-3">
                {filteredGroups.map((g) => {
                  const isCollapsed = !!collapsed[g.group] && !search.trim();
                  const groupMapped = g.columns.filter((c) => columnMap[c.field]).length;
                  return (
                    <div key={g.group} className="border border-slate-200 rounded-lg overflow-hidden">
                      <button onClick={() => setCollapsed((p) => ({ ...p, [g.group]: !p[g.group] }))}
                        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-50 text-left hover:bg-slate-100">
                        {isCollapsed ? <ChevronRight className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                        <span className="text-xs font-semibold text-slate-700">{g.group}</span>
                        <span className="text-[11px] text-slate-400">{groupMapped} / {g.columns.length} mapped</span>
                      </button>
                      {!isCollapsed && (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1.5 px-3 py-2.5">
                          {g.columns.map((c) => {
                            const mappedTo = columnMap[c.field] || "";
                            const sample = mappedTo && extracted.sample_rows[0] ? extracted.sample_rows[0][mappedTo] : null;
                            return (
                              <div key={c.field} className="flex items-center gap-2">
                                <div className="w-40 shrink-0">
                                  <span className="text-[11px] font-medium text-slate-700 truncate block" title={c.header}>{c.header}</span>
                                </div>
                                <div className="relative flex-1 min-w-0">
                                  <select value={mappedTo} onChange={(e) => setMap(c.field, e.target.value)}
                                    className={`w-full border rounded-md pl-2 pr-6 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-blue-400 ${mappedTo ? "border-emerald-200 bg-emerald-50/40 text-slate-700" : "border-slate-200 bg-white text-slate-400"}`}>
                                    <option value={SKIP}>— not in file —</option>
                                    {extracted.xls_columns.map((x) => <option key={x} value={x}>{x}</option>)}
                                  </select>
                                </div>
                                {mappedTo
                                  ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                                  : <span className="w-3.5 shrink-0" />}
                                {mappedTo && sample != null && sample !== "" && (
                                  <span className="text-[10px] text-slate-400 truncate max-w-[80px] shrink-0" title={String(sample)}>{String(sample)}</span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* STEP 3 — PREVIEW */}
          {step === "preview" && extracted && (
            <div>
              <p className="text-xs text-slate-500 mb-3">
                Preview of the first {previewRows.length} of {extracted.total_rows.toLocaleString()} rows, mapped as configured.
                Confirm to ingest all {extracted.total_rows.toLocaleString()} rows in the background.
              </p>
              {/* Not blocking — some exports carry the period in the file name — but
                  worth saying before ingesting tens of thousands of undated rows. */}
              {dateMissing && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-3 text-xs text-amber-700">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>No date column is mapped (Transaction Date, BookingDate or PaymentDtm). These rows will import without a date, so they won&apos;t appear in any period filter.</span>
                </div>
              )}
              <div className="border border-slate-200 rounded-xl overflow-hidden">
                <div className="overflow-x-auto max-h-[52vh]">
                  <table className="text-left border-collapse text-sm">
                    <thead className="sticky top-0">
                      <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
                        {coreColsForPreview.map((c) => <th key={c.field} className="px-3 py-2 font-semibold whitespace-nowrap">{c.header}</th>)}
                        <th className="px-3 py-2 font-semibold whitespace-nowrap">Taxes Total</th>
                        <th className="px-3 py-2 font-semibold whitespace-nowrap">Taxes</th>
                        <th className="px-3 py-2 font-semibold whitespace-nowrap">Segments</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewRows.length === 0 ? (
                        <tr><td colSpan={coreColsForPreview.length + 3} className="px-3 py-8 text-center text-slate-400">No preview rows.</td></tr>
                      ) : previewRows.map((r, i) => (
                        <tr key={i} className="border-b border-slate-100">
                          {coreColsForPreview.map((c) => {
                            const v = r.core[c.field];
                            return <td key={c.field} className="px-3 py-1.5 text-xs text-slate-700 whitespace-nowrap max-w-[200px] truncate" title={v || undefined}>{v || <span className="text-slate-300">—</span>}</td>;
                          })}
                          <td className="px-3 py-1.5 text-xs text-slate-700 whitespace-nowrap tabular-nums">{r.taxesTotal || <span className="text-slate-300">—</span>}</td>
                          <td className="px-3 py-1.5 text-xs text-slate-500 whitespace-nowrap max-w-[260px] truncate" title={r.taxes}>{r.taxes || <span className="text-slate-300">—</span>}</td>
                          <td className="px-3 py-1.5 text-xs text-slate-500 whitespace-nowrap max-w-[200px] truncate" title={r.segments}>{r.segments || <span className="text-slate-300">—</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* STEP 4 — PROGRESS */}
          {step === "progress" && statusData && (
            <div className="py-10 flex flex-col items-center text-center">
              {failed ? (
                <>
                  <div className="w-14 h-14 rounded-full bg-red-50 flex items-center justify-center mb-4"><AlertTriangle className="w-7 h-7 text-red-500" /></div>
                  <p className="text-sm font-semibold text-slate-800 mb-1">Import failed</p>
                  <p className="text-xs text-red-500 max-w-md">{statusData.error || "Something went wrong during ingestion."}</p>
                </>
              ) : (
                <>
                  <Loader2 className="w-10 h-10 text-blue-500 animate-spin mb-4" />
                  <p className="text-sm font-semibold text-slate-800 mb-1">
                    {statusData.status === "pending" ? "Queued for processing…" : "Importing rows…"}
                  </p>
                  <p className="text-xs text-slate-500 mb-4">{statusData.processed_rows.toLocaleString()} of {statusData.total_rows.toLocaleString()} rows</p>
                  <div className="h-2 w-72 rounded-full bg-slate-100 overflow-hidden">
                    <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${Math.max(3, statusData.progress_pct)}%` }} />
                  </div>
                  <p className="text-[11px] text-slate-400 mt-3">You can close this dialog — the import continues in the background.</p>
                </>
              )}
            </div>
          )}

          {/* STEP 5 — DONE */}
          {step === "done" && statusData && (() => {
            const saved = statusData.processed_rows;
            const exp = statusData.expected_rows;
            const matches = exp != null && saved === exp;
            const diff = exp != null ? saved - exp : 0;
            return (
            <div className="py-12 flex flex-col items-center text-center">
              <div className={`w-14 h-14 rounded-full flex items-center justify-center mb-4 ${exp != null && !matches ? "bg-amber-50" : "bg-emerald-50"}`}>
                <PartyPopper className={`w-7 h-7 ${exp != null && !matches ? "text-amber-500" : "text-emerald-500"}`} />
              </div>
              <p className="text-sm font-semibold text-slate-800 mb-1">Import complete</p>
              <p className="text-xs text-slate-500">{saved.toLocaleString()} rows saved to {title}.</p>
              {exp != null && (
                matches ? (
                  <div className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-xs font-medium text-emerald-700">
                    <CheckCircle2 className="w-4 h-4" /> All {exp.toLocaleString()} expected records saved.
                  </div>
                ) : (
                  <div className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-xs font-medium text-amber-700">
                    <AlertTriangle className="w-4 h-4" /> Expected {exp.toLocaleString()}, saved {saved.toLocaleString()} — {Math.abs(diff).toLocaleString()} {diff < 0 ? "missing" : "extra"}.
                  </div>
                )
              )}
            </div>
            );
          })()}
        </div>

        {/* FOOTER */}
        <div className="flex items-center justify-between gap-2 px-5 py-3.5 border-t border-slate-100">
          <div>
            {(step === "mapping" || step === "preview") && (
              <button onClick={() => setStep(step === "preview" ? "mapping" : "upload")} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"><ArrowLeft className="w-3.5 h-3.5" /> Back</button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {step === "upload" && (
              <>
                <button onClick={onClose} className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
                <button onClick={doExtract} disabled={!file || uploading} className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
                  {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />} Continue
                </button>
              </>
            )}
            {step === "mapping" && (
              // Deliberately NOT disabled when the mapping is incomplete — a dead
              // button explains nothing. Clicking it names what is missing.
              <button onClick={() => { if (checkMapping()) setStep("preview"); }} className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
                Preview <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
            {step === "preview" && (
              <button onClick={doConfirm} className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
                <Upload className="w-3.5 h-3.5" /> Confirm &amp; Save
              </button>
            )}
            {step === "progress" && (
              <button onClick={failed ? () => setStep("preview") : onDone} className="px-4 py-1.5 text-xs font-semibold text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50">
                {failed ? "Back" : "Close (runs in background)"}
              </button>
            )}
            {step === "done" && (
              <button onClick={onDone} className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700">
                <CheckCircle2 className="w-3.5 h-3.5" /> Done
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
