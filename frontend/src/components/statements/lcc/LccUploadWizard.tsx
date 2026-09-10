"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  X, Upload, CheckCircle2, Loader2, Search, ChevronDown, ChevronRight,
  AlertTriangle, ArrowLeft, ArrowRight, Wand2, Eraser, PartyPopper,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import { notifyRequired } from "@/lib/requiredFields";
import MultiSelectDropdown from "@/components/ui/MultiSelectDropdown";
import Dropzone from "@/components/statements/Dropzone";
import { type TenantAirlineOpt, sameAirlineOnly, toOptions } from "@/lib/tenantAirlineOptions";

type Step = "upload" | "mapping" | "preview" | "progress" | "done";

type StdCol = { header: string; field: string; role: "core" | "tax" | "leg"; dtype: string; leg_no?: number; slot?: string };
type StdGroup = { group: string; columns: StdCol[] };
type SampleRow = Record<string, string | null>;

/** Which half of a split statement a file is. `single` is the ordinary one-file case. */
type FileRole = "single" | "account" | "pax";

/** One uploaded file's mapping pane, as the server prepared it. For a passenger
 *  report the columns and samples are POST-merge, so what you map is what is stored. */
type FileBlock = {
  role: FileRole;
  role_label: string;
  file_name: string;
  header_row: number;
  source_rows: number;
  xls_columns: string[];
  suggested_mapping: Record<string, string>;   // {field: column}
  sample_rows: SampleRow[];
  matched_columns: number;
  is_template_match: boolean;
};

type ExtractResp = {
  batch_id: string;
  source_format: string;
  source_rows: number;
  standard_total: number;
  primary_role: FileRole;
  files: FileBlock[];
  // Flattened primary — still sent, and still what the older single-file path read.
  file_name: string;
  total_rows: number;
};

type MergeStats = {
  source_rows?: number; account_rows?: number; pax_rows?: number;
  skipped_not_ag?: number; pnrs_indexed?: number;
  enriched_account_rows?: number; unmatched_account_rows?: number;
  matched_without_fare?: number; tax_derived?: number;
  duplicate_pax_lines?: number; repeated_legs?: number; legs_truncated?: number;
  movement_counts?: Record<string, number>;
  unknown_notes?: Record<string, number>;
  currencies_seen?: string[];
};

type StatusResp = {
  batch_id: string; status: string; total_rows: number; processed_rows: number;
  expected_rows: number | null; source_rows: number | null; merge_stats: MergeStats | null;
  progress_pct: number; error: string | null;
};

const SKIP = "";   // "— not in file —"

type RequiredGroup = { label: string; fields: string[]; headers: string };

/**
 * Mapping rules, PER FILE ROLE.
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
 * Which HEADER carries it differs by file — an account statement's money is
 * `ForeignAmount` — but it always lands in the same field, `total`, because that
 * is the one `_bill_kind` and the invoice read.
 *
 * DATE is a warning only — some exports genuinely carry the period in the file
 * name rather than per row.
 */
const REQUIRED_BY_ROLE: Record<FileRole, RequiredGroup[]> = {
  single: [
    { label: "a booking identifier", fields: ["record_locator", "gds_record_locator"], headers: "RecordLocator or GDS_recordlocator" },
    { label: "an amount", fields: ["total", "base_fare"], headers: "Total or BaseFare" },
  ],
  pax: [
    { label: "a booking identifier", fields: ["record_locator", "gds_record_locator"], headers: "RecordLocator" },
    { label: "an amount", fields: ["total", "base_fare"], headers: "TotalFare or BaseFare" },
  ],
  account: [
    { label: "a PNR", fields: ["record_locator", "gds_record_locator"], headers: "PNR" },
    { label: "the transaction amount", fields: ["total"], headers: "ForeignAmount" },
  ],
};
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
  // One mapping per file. The two halves of a split statement share no headers, so
  // one map could not describe both.
  const [columnMaps, setColumnMaps] = useState<Record<string, Record<string, string>>>({});
  const [activeRole, setActiveRole] = useState<FileRole>("single");

  // Upload state. Two slots: most statements fill only the first, but an airline that
  // splits its export into an account file and a passenger file needs both, and
  // neither is usable alone. The server decides which is which from the headers, so
  // the order they are dropped in does not matter.
  const [fileA, setFileA] = useState<File | null>(null);
  const [fileB, setFileB] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [expectedRows, setExpectedRows] = useState("");   // user-declared record count (optional)
  // Airline — REQUIRED. An LCC export names no carrier (no airline column, and bare
  // flight numbers in Segments), so the user's Airline Master ids are the only thing
  // that identifies it. Sent with /extract so a batch is never airline-less.
  // Several ids, because one statement usually covers more than one of the user's
  // logins for that carrier — but all of one carrier; see lib/tenantAirlineOptions.ts.
  const [airlines, setAirlines] = useState<TenantAirlineOpt[]>([]);
  const [tenantAirlineIds, setTenantAirlineIds] = useState<number[]>([]);
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

  // The user's Airline Master, active entries only.
  useEffect(() => {
    api.get<TenantAirlineOpt[]>("/tenant-airlines/", { params: { active: true } })
      .then((r) => setAirlines(r.data))
      .catch(() => toast.error("Failed to load your Airline Master."));
  }, []);

  // Once one id is picked the list narrows to that carrier's other ids — the server
  // refuses a mixed selection, so offering one would only produce a 400.
  const airlineChoices = useMemo(
    () => sameAirlineOnly(airlines, tenantAirlineIds),
    [airlines, tenantAirlineIds],
  );

  // Memoised, not written inline: `?? []` would mint a fresh array every render and
  // re-run every callback that depends on it.
  const files: FileBlock[] = useMemo(() => extracted?.files ?? [], [extracted]);
  const active: FileBlock | undefined =
    files.find((f) => f.role === activeRole) ?? files[0];
  // Memoised on the ROLE, not written inline: `?? {}` would mint a fresh object on
  // every render and re-run the preview fold with it.
  const columnMap = useMemo(
    () => columnMaps[active?.role ?? ""] ?? {},
    [columnMaps, active?.role],
  );

  const allCols: StdCol[] = useMemo(() => groups.flatMap((g) => g.columns), [groups]);
  const totalStd = allCols.length || extracted?.standard_total || 0;
  const mappedCount = Object.values(columnMap).filter(Boolean).length;

  // A passenger file sitting beside an account file is a LOOKUP — it produces no
  // rows of its own — so it has nothing to require. Demanding a mapping of it would
  // block the upload on a pane that does not write anything.
  const isLookup = useCallback(
    (f: FileBlock) => f.role === "pax" && files.some((x) => x.role === "account"),
    [files],
  );

  const missingFor = useCallback((f: FileBlock): string[] => {
    if (isLookup(f)) return [];
    const map = columnMaps[f.role] ?? {};
    return (REQUIRED_BY_ROLE[f.role] ?? REQUIRED_BY_ROLE.single)
      .filter((g) => !g.fields.some((fld) => map[fld]))
      .map((g) => `${g.label} (${g.headers})`);
  }, [columnMaps, isLookup]);

  const missingRequiredGroups = active ? missingFor(active) : [];
  const dateMissing = !DATE_FIELDS.some((f) => columnMap[f]);

  /** Guard for both Preview and Confirm — the mapping is what makes the rows usable.
   *  Checks EVERY file, not just the one on screen, and jumps to the one at fault. */
  const checkMapping = (): boolean => {
    for (const f of files) {
      if (isLookup(f)) continue;
      const map = columnMaps[f.role] ?? {};
      const core = allCols.filter((c) => c.role === "core" && map[c.field]).length;
      const where = files.length > 1 ? ` in the ${f.role_label.toLowerCase()}` : "";
      if (core === 0) {
        setActiveRole(f.role);
        return notifyRequired(`Map at least one Core column${where} — mapping only taxes or legs would import rows with no ticket data on them.`);
      }
      const missing = missingFor(f);
      if (missing.length) {
        setActiveRole(f.role);
        return notifyRequired(
          missing.length === 1
            ? `Map ${missing[0]}${where} before continuing.`
            : `Map ${missing.join(" and ")}${where} before continuing.`
        );
      }
    }
    return true;
  };

  // ── Upload ─────────────────────────────────────────────────────────────────
  const chosen = [fileA, fileB].filter(Boolean) as File[];

  const doExtract = async () => {
    if (!chosen.length) { notifyRequired("Choose a statement file (.xlsx, .xls or .csv) to continue."); return; }
    if (!tenantAirlineIds.length) {
      notifyRequired("Select the airline ID(s) this statement belongs to — the file itself doesn't say.");
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      // Repeated field, one per file — how FastAPI reads a list from form data.
      for (const f of chosen) fd.append("files", f);
      for (const id of tenantAirlineIds) fd.append("tenant_airline_ids", String(id));
      const { data } = await api.post<ExtractResp>(`${apiBase}/extract`, fd);
      setExtracted(data);
      setColumnMaps(Object.fromEntries(data.files.map((f) => [f.role, f.suggested_mapping || {}])));
      setActiveRole(data.primary_role);
      setStep("mapping");
    } catch (e) { toast.error(errMsg(e, "Could not read the file.")); }
    finally { setUploading(false); }
  };

  // ── Mapping ──────────────────────────────────────────────────────────────
  const setMap = (field: string, xlsCol: string) =>
    setColumnMaps((prev) => {
      const role = active?.role ?? "single";
      const next = { ...(prev[role] ?? {}) };
      if (xlsCol) next[field] = xlsCol; else delete next[field];
      return { ...prev, [role]: next };
    });
  const autoMapAll = () =>
    setColumnMaps((prev) => ({ ...prev, [active?.role ?? "single"]: active?.suggested_mapping ?? {} }));
  const clearAll = () =>
    setColumnMaps((prev) => ({ ...prev, [active?.role ?? "single"]: {} }));

  const filteredGroups: StdGroup[] = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({ ...g, columns: g.columns.filter((c) => c.header.toLowerCase().includes(q) || c.field.toLowerCase().includes(q)) }))
      .filter((g) => g.columns.length > 0);
  }, [groups, search]);

  // ── Preview (folded client-side from the active file's sample rows) ──────
  const previewRows = useMemo(() => {
    if (!active) return [];
    const coreCols = allCols.filter((c) => c.role === "core");
    const taxCols = allCols.filter((c) => c.role === "tax");
    const legCols = allCols.filter((c) => c.role === "leg");
    return active.sample_rows.slice(0, 50).map((sr) => {
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
  }, [active, columnMap, allCols]);

  const coreColsForPreview = allCols.filter((c) => c.role === "core");

  // ── Confirm + progress polling ───────────────────────────────────────────
  const doConfirm = async () => {
    if (!extracted) { notifyRequired("Nothing to import — upload a file first."); return; }
    // Re-checked here, not just on the Preview button: this is the call that
    // actually writes rows, and the user can reach it after editing the mapping.
    if (!checkMapping()) { setStep("mapping"); return; }
    try {
      await api.post(`${apiBase}/confirm`, {
        batch_id: extracted.batch_id, column_maps: columnMaps, expected_rows: expectedNum,
      });
      setStatusData({
        batch_id: extracted.batch_id, status: "pending", total_rows: extracted.source_rows,
        processed_rows: 0, expected_rows: expectedNum, source_rows: extracted.source_rows,
        merge_stats: null, progress_pct: 0, error: null,
      });
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
  const multi = files.length > 1;

  /** Role tabs, shown only when there is more than one file to map.
   *  A plain function, not a nested component: declaring a component inside a
   *  component gives React a new type every render and remounts the subtree. */
  const roleTabs = () => !multi ? null : (
    <div className="flex items-center gap-1 mb-3 border-b border-slate-200">
      {files.map((f) => {
        const on = f.role === active?.role;
        const bad = missingFor(f).length > 0;
        return (
          <button key={f.role} onClick={() => setActiveRole(f.role)}
            className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold border-b-2 -mb-px ${on ? "border-blue-600 text-blue-600" : "border-transparent text-slate-400 hover:text-slate-600"}`}>
            {f.role_label}
            {bad && <AlertTriangle className="w-3 h-3 text-amber-500" />}
            <span className="font-normal text-slate-400">{f.source_rows.toLocaleString()} rows</span>
          </button>
        );
      })}
    </div>
  );

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
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Dropzone
                  file={fileA} onPick={setFileA}
                  label="Drop your statement export here"
                  note="The whole statement, or either half of a split one"
                />
                {/* Second slot, optional. Some airlines — Air India Express among
                    them — issue the statement as an account file plus a passenger
                    file that only mean anything joined on PNR. Which is which is
                    read from the headers, so either can go in either slot. */}
                <Dropzone
                  file={fileB} onPick={setFileB}
                  label="Second file (optional)"
                  note="Only if your airline splits the statement in two"
                  compact={!fileB}
                />
              </div>
              {chosen.length === 2 && (
                <p className="text-[11px] text-slate-500 mt-2">
                  Both files will be merged into one statement, matched on PNR. We&apos;ll work out
                  which is the account statement and which is the passenger report from their columns.
                </p>
              )}

              {/* Airline — REQUIRED. Nothing in an LCC export identifies the carrier:
                  there is no airline column and the flight numbers are bare, so this
                  selection is the only source of it. */}
              <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50/60 px-3.5 py-3">
                <div className="flex flex-wrap items-start gap-2.5">
                  <label className="text-xs font-semibold text-slate-700 pt-2">
                    Airline <span className="text-red-500">*</span>
                  </label>
                  <div className="min-w-64 flex-1 max-w-md">
                    <MultiSelectDropdown
                      options={toOptions(airlineChoices.options)}
                      selected={tenantAirlineIds}
                      onChange={setTenantAirlineIds}
                      disabled={airlines.length === 0}
                      placeholder={airlines.length ? "Select your airline ID(s)…" : "No airline IDs yet"}
                      emptyText="No matching ID"
                    />
                    {/* Say why the list is short, or the narrowing reads as data loss. */}
                    {airlineChoices.lockedAirline && (
                      <p className="text-[11px] text-slate-400 mt-1.5">
                        Showing {airlineChoices.lockedAirline} IDs — a statement carries one carrier,
                        so clear the selection to pick a different airline.
                      </p>
                    )}
                  </div>
                  <span className="text-[11px] text-slate-400 pt-2 flex-1 min-w-48">
                    An LCC export doesn&apos;t name the carrier, so pick the ID you gave it. Add every
                    ID this statement covers.
                  </span>
                </div>
                {airlines.length === 0 && (
                  <p className="text-[11px] text-amber-600 mt-2">
                    Your Airline Master is empty. Add the airline under User Master → Airline Master first.
                  </p>
                )}
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
                  How many lines are in your file(s)? We&apos;ll confirm we read that many.
                </span>
              </div>

              <p className="text-[11px] text-slate-400 mt-3">Next you&apos;ll map the file&apos;s columns to the standard template, preview a sample, then save. The original file is stored.</p>
            </div>
          )}

          {/* STEP 2 — MAPPING */}
          {step === "mapping" && active && (
            <div>
              {roleTabs()}
              <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 mb-3 text-xs ${active.is_template_match ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
                {active.is_template_match
                  ? <><CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /><span>Looks like the standard template — every column in <b>{active.file_name}</b> matched a standard column. Review and adjust if needed.</span></>
                  : <><AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /><span>{mappedCount} of {totalStd} standard columns auto-matched from <b>{active.file_name}</b>. Map the rest below (or leave them unmapped).</span></>}
              </div>

              {active.role === "account" && multi && (
                <p className="text-[11px] text-slate-500 mb-3">
                  These are the columns <i>after</i> merging: one row per transaction, with the
                  passenger, booking date, sectors and base fare joined in from the passenger
                  report on PNR, and <b>Tax Total</b> worked out as the amount minus the base fare.
                  Only rows whose payment method is <b>AG</b> are imported — that leaves the
                  statement-balance lines out. What you map here is what gets stored.
                </p>
              )}
              {active.role === "pax" && multi && (
                <p className="text-[11px] text-slate-500 mb-3">
                  This file is a <b>lookup</b>, not a second set of rows — it supplies the
                  passenger, the sectors and the base fare to the account statement, matched on
                  PNR. Nothing here is imported on its own, so there is nothing to map.
                </p>
              )}
              {active.role === "pax" && !multi && (
                <p className="text-[11px] text-slate-500 mb-3">
                  Uploaded on its own, this imports as an ordinary statement: one row per
                  passenger, their flights folded into the leg columns. Add the account statement
                  alongside it to get the transaction amounts.
                </p>
              )}

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
                            const sample = mappedTo && active.sample_rows[0] ? active.sample_rows[0][mappedTo] : null;
                            return (
                              <div key={c.field} className="flex items-center gap-2">
                                <div className="w-40 shrink-0">
                                  <span className="text-[11px] font-medium text-slate-700 truncate block" title={c.header}>{c.header}</span>
                                </div>
                                <div className="relative flex-1 min-w-0">
                                  <select value={mappedTo} onChange={(e) => setMap(c.field, e.target.value)}
                                    className={`w-full border rounded-md pl-2 pr-6 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-blue-400 ${mappedTo ? "border-emerald-200 bg-emerald-50/40 text-slate-700" : "border-slate-200 bg-white text-slate-400"}`}>
                                    <option value={SKIP}>— not in file —</option>
                                    {active.xls_columns.map((x) => <option key={x} value={x}>{x}</option>)}
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
          {step === "preview" && active && extracted && (
            <div>
              {roleTabs()}
              <p className="text-xs text-slate-500 mb-3">
                {multi
                  ? <>Preview of the merged <b>{active.role_label.toLowerCase()}</b> rows — {previewRows.length} shown, from {active.source_rows.toLocaleString()} source lines. A merge writes fewer rows than it reads.</>
                  : <>Preview of the first {previewRows.length} of {extracted.source_rows.toLocaleString()} rows, mapped as configured. Confirm to ingest them all in the background.</>}
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
                        {/* Distinct from the mappable "Tax Total" column above: this is
                            the sum of the per-code tax columns, which an export that
                            ships one lump-sum tax figure will not have. */}
                        <th className="px-3 py-2 font-semibold whitespace-nowrap">Taxes Σ</th>
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
            // Compared against SOURCE lines, not rows written. A merge collapses
            // passenger-per-segment lines into passenger rows, so comparing the two
            // would report a shortfall on every merged upload that isn't one.
            const read = statusData.source_rows ?? saved;
            const matches = exp != null && read === exp;
            const diff = exp != null ? read - exp : 0;
            const st = statusData.merge_stats;
            const unknown = Object.entries(st?.unknown_notes ?? {});
            return (
            <div className="py-10 flex flex-col items-center text-center">
              <div className={`w-14 h-14 rounded-full flex items-center justify-center mb-4 ${exp != null && !matches ? "bg-amber-50" : "bg-emerald-50"}`}>
                <PartyPopper className={`w-7 h-7 ${exp != null && !matches ? "text-amber-500" : "text-emerald-500"}`} />
              </div>
              <p className="text-sm font-semibold text-slate-800 mb-1">Import complete</p>
              {st && (st.account_rows ?? 0) > 0 ? (
                <p className="text-xs text-slate-500">
                  {read.toLocaleString()} source lines → {(st.account_rows ?? 0).toLocaleString()} transactions
                  saved to {title}
                  {(st.skipped_not_ag ?? 0) > 0 &&
                    <> ({(st.skipped_not_ag ?? 0).toLocaleString()} non-AG lines left out)</>}.
                </p>
              ) : (
                <p className="text-xs text-slate-500">{saved.toLocaleString()} rows saved to {title}.</p>
              )}

              {exp != null && (
                matches ? (
                  <div className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-xs font-medium text-emerald-700">
                    <CheckCircle2 className="w-4 h-4" /> All {exp.toLocaleString()} expected records read.
                  </div>
                ) : (
                  <div className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-xs font-medium text-amber-700">
                    <AlertTriangle className="w-4 h-4" /> Expected {exp.toLocaleString()}, read {read.toLocaleString()} — {Math.abs(diff).toLocaleString()} {diff < 0 ? "missing" : "extra"}.
                  </div>
                )
              )}

              {/* What the merge did. Only the numbers that need a person to look at
                  something are shown — a clean merge says nothing. */}
              {st && (
                <div className="mt-4 w-full max-w-md space-y-1.5 text-left">
                  {(st.tax_derived ?? 0) > 0 && (
                    <p className="text-[11px] text-slate-500">
                      {(st.tax_derived ?? 0).toLocaleString()} transactions matched a booking in the
                      passenger report and got a base fare, passenger and sectors — tax was worked
                      out as the amount minus the base fare.
                    </p>
                  )}
                  {(st.unmatched_account_rows ?? 0) > 0 && (
                    <p className="text-[11px] text-amber-600">
                      {(st.unmatched_account_rows ?? 0).toLocaleString()} transactions had no matching PNR in
                      the passenger report, so they carry an amount but no base fare or tax —
                      usually because the two files cover different dates.
                    </p>
                  )}
                  {(st.matched_without_fare ?? 0) > 0 && (
                    <p className="text-[11px] text-amber-600">
                      {(st.matched_without_fare ?? 0).toLocaleString()} transactions matched a PNR that
                      carried no base fare, so their tax is blank rather than the whole amount.
                    </p>
                  )}
                  {(st.duplicate_pax_lines ?? 0) > 0 && (
                    <p className="text-[11px] text-slate-500">
                      {(st.duplicate_pax_lines ?? 0).toLocaleString()} duplicate lines were dropped rather than counted twice.
                    </p>
                  )}
                  {(st.legs_truncated ?? 0) > 0 && (
                    <p className="text-[11px] text-amber-600">
                      {(st.legs_truncated ?? 0).toLocaleString()} bookings have more than five flights — the fares are
                      complete, but only the first five sectors are shown.
                    </p>
                  )}
                  {unknown.length > 0 && (
                    <p className="text-[11px] text-amber-600">
                      Unrecognised transaction note{unknown.length > 1 ? "s" : ""}:{" "}
                      {unknown.map(([k, n]) => `“${k}” (${n})`).join(", ")}. Those rows imported as
                      movements of an unknown kind — worth a look.
                    </p>
                  )}
                  {(st.currencies_seen?.length ?? 0) > 1 && (
                    <p className="text-[11px] text-red-600">
                      This upload mixes {st.currencies_seen?.join(", ")}. Billing can&apos;t invoice more than
                      one currency at a time — split the statement before sending it to billing.
                    </p>
                  )}
                </div>
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
                <button onClick={doExtract} disabled={!chosen.length || uploading} className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
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
