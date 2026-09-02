"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle, ArrowRight, Check, ChevronRight, Download, FileSpreadsheet,
  Info, RefreshCw, Save, Upload, X,
} from "lucide-react";
import api from "@/lib/api";
import { INHERITED_FIELDS, PARTY, isBlankInherited, type PartyKind } from "@/lib/party";
import {
  IMPORT_FIELDS, applyMapping, autoMap, parseWorkbook, toPayload, validateRow,
  type ImportField, type ParsedSheet, type ReviewRow,
} from "@/lib/partyImport";

type BulkResult = { total: number; success: number; failed: number; errors: string[] };

type Step = 1 | 2 | 3 | 4;
const STEP_LABELS = ["Upload File", "Column Mapping", "Review & Confirm", "Done"];

const BTN_PRIMARY =
  "bg-[#1e3a5f] hover:bg-[#16304f] text-white rounded-lg px-5 py-2 text-sm font-semibold disabled:opacity-50 flex items-center justify-center gap-2";
const BTN_GHOST =
  "border border-gray-200 text-gray-600 rounded-lg px-4 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-50";

/**
 * Bulk Excel import for Employee Master / Corporate Master, as a four-step wizard:
 *
 *   1 Upload File       pick the sheet; it is read in the browser (lib/partyImport)
 *   2 Column Mapping    match the file's headers to our fields, auto-guessed
 *   3 Review & Confirm  see and fix every mapped row before anything is written
 *   4 Done              what saved, and what did not
 *
 * Nothing reaches the server until step 3's Confirm & Save, which posts the
 * reviewed rows to /{resource}/bulk-create as JSON. The older one-shot
 * /{resource}/bulk-upload endpoint is untouched and still serves the template.
 */
export default function PartyUploadModal({
  kind,
  onClose,
  onSaved,
}: {
  kind: PartyKind;
  onClose: () => void;
  onSaved: () => void;
}) {
  const cfg = PARTY[kind];
  const fields = IMPORT_FIELDS[kind];

  const [step, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  const [sheet, setSheet] = useState<ParsedSheet | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<ReviewRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<BulkResult | null>(null);

  const requiredFields = fields.filter((f) => f.required);
  const unmappedRequired = requiredFields.filter((f) => !mapping[f.key]);

  // Recomputed on every keystroke in review — the grid is small and the check is
  // pure, so there is nothing to invalidate or keep in sync.
  const rowErrors = useMemo(
    () => rows.map((r) => validateRow(fields, r.values)),
    [rows, fields]
  );
  const includedIdx = rows.map((_, i) => i).filter((i) => rows[i].included);
  const badIdx = includedIdx.filter((i) => Object.keys(rowErrors[i]).length > 0);
  const savableCount = includedIdx.length - badIdx.length;

  const handleTemplateDownload = async () => {
    setError("");
    try {
      const res = await api.get(`/${cfg.resource}/template`, { responseType: "blob" });
      const url = window.URL.createObjectURL(res.data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = cfg.templateFile;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      setError("Template download failed.");
    }
  };

  const handleFile = async (picked: File | null) => {
    setFile(picked);
    setSheet(null);
    setError("");
    setResult(null);
    if (!picked) return;
    try {
      const parsed = parseWorkbook(await picked.arrayBuffer());
      if (!parsed.rows.length) {
        setError("That sheet has headers but no data rows.");
        return;
      }
      setSheet(parsed);
      setMapping(autoMap(fields, parsed.columns));
    } catch (e) {
      setError(
        e instanceof Error && e.message ? e.message : "Could not read that file. Use a valid .xlsx or .xls."
      );
    }
  };

  const goToReview = () => {
    if (!sheet) return;
    setRows(applyMapping(fields, mapping, sheet));
    setStep(3);
  };

  const editCell = (rowIdx: number, key: string, value: string) =>
    setRows((prev) =>
      prev.map((r, i) => (i === rowIdx ? { ...r, values: { ...r.values, [key]: value } } : r))
    );

  const toggleRow = (rowIdx: number) =>
    setRows((prev) => prev.map((r, i) => (i === rowIdx ? { ...r, included: !r.included } : r)));

  const handleSave = async () => {
    const payloadRows = includedIdx
      .filter((i) => Object.keys(rowErrors[i]).length === 0)
      .map((i) => toPayload(fields, rows[i].values));
    if (!payloadRows.length) {
      setError("There are no valid rows to save.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post<BulkResult>(`/${cfg.resource}/bulk-create`, { rows: payloadRows });
      setResult(data);
      setStep(4);
      if (data.success > 0) onSaved();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Upload className="w-4 h-4 text-[#1e3a5f]" />
            </div>
            <h2 className="text-sm font-bold text-gray-900">Import {cfg.masterPlural}</h2>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="px-6 py-3 border-b border-gray-100">
          <StepBar step={step} />
        </div>

        <div className="px-6 py-4 overflow-y-auto flex-1">
          {step === 1 && (
            <div className="space-y-3">
              <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2.5 flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-[#1e3a5f]">Download Excel Template</p>
                  <p className="text-[10px] text-blue-500 mt-0.5">Columns: {cfg.templateColumns}</p>
                  {cfg.templateNote && (
                    <p className="text-[10px] text-blue-600/80 mt-1">{cfg.templateNote}</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleTemplateDownload}
                  className="flex items-center gap-1 text-[#1e3a5f] hover:opacity-80 text-xs font-medium whitespace-nowrap ml-3"
                >
                  <Download className="w-3.5 h-3.5" /> Template
                </button>
              </div>

              <p className="text-[11px] text-gray-500">
                The template is the easy path, but any spreadsheet works — you match its columns to ours in
                the next step.
              </p>

              <div>
                <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                  Select XLS / XLSX File
                </label>
                <input
                  type="file"
                  accept=".xls,.xlsx"
                  onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 file:mr-3 file:text-xs file:font-semibold file:bg-blue-50 file:text-[#1e3a5f] file:border-0 file:rounded file:px-2 file:py-1 bg-gray-50 focus:outline-none"
                />
              </div>

              {sheet && (
                <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-green-50 border border-green-200 text-[11px] text-green-800">
                  <FileSpreadsheet className="w-4 h-4 shrink-0 text-green-600" />
                  <span>
                    <span className="font-semibold">{file?.name}</span> — sheet &ldquo;{sheet.sheetName}&rdquo;,{" "}
                    {sheet.columns.length} columns, {sheet.rows.length}{" "}
                    {sheet.rows.length === 1 ? "row" : "rows"} (header on row {sheet.headerRow}).
                  </span>
                </div>
              )}
            </div>
          )}

          {step === 2 && sheet && (
            <MappingStep
              fields={fields}
              sheet={sheet}
              mapping={mapping}
              onChange={(key, col) =>
                setMapping((prev) => {
                  const next = { ...prev };
                  // One sheet column feeds one field — picking it here takes it
                  // off whichever field held it, so no column is read twice.
                  if (col) for (const k of Object.keys(next)) if (next[k] === col) delete next[k];
                  if (col) next[key] = col;
                  else delete next[key];
                  return next;
                })
              }
            />
          )}

          {step === 3 && (
            <ReviewStep
              fields={fields}
              rows={rows}
              rowErrors={rowErrors}
              onEdit={editCell}
              onToggle={toggleRow}
              savableCount={savableCount}
              badCount={badIdx.length}
              excludedCount={rows.length - includedIdx.length}
              kind={kind}
            />
          )}

          {step === 4 && result && (
            <div
              className={`rounded-lg border px-4 py-3 text-xs space-y-1 ${
                result.failed > 0 ? "bg-yellow-50 border-yellow-200" : "bg-green-50 border-green-200"
              }`}
            >
              <p className="font-semibold text-sm">
                {result.success} of {result.total} {result.total === 1 ? "row" : "rows"} saved
              </p>
              {result.failed > 0 && (
                <p className="text-[11px] text-gray-600">
                  {result.failed} rejected by the server. Nothing else was changed.
                </p>
              )}
              {result.errors.slice(0, 8).map((e, i) => (
                <p key={i} className="text-[11px] text-red-500">{e}</p>
              ))}
              {result.errors.length > 8 && (
                <p className="text-[11px] text-gray-400">…and {result.errors.length - 8} more</p>
              )}
            </div>
          )}

          {error && <p className="text-[11px] text-red-500 mt-3">{error}</p>}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex gap-3">
          {step === 1 && (
            <>
              <button onClick={onClose} className={`${BTN_GHOST} flex-1`}>Cancel</button>
              <button onClick={() => setStep(2)} disabled={!sheet} className={`${BTN_PRIMARY} flex-1`}>
                Map Columns <ArrowRight className="w-4 h-4" />
              </button>
            </>
          )}
          {step === 2 && (
            <>
              <button onClick={() => setStep(1)} className={BTN_GHOST}>← Back</button>
              <button
                onClick={goToReview}
                disabled={unmappedRequired.length > 0}
                className={`${BTN_PRIMARY} flex-1`}
                title={
                  unmappedRequired.length
                    ? `Map ${unmappedRequired.map((f) => f.label).join(", ")} to continue`
                    : undefined
                }
              >
                <ArrowRight className="w-4 h-4" /> Apply Mapping &amp; Review
              </button>
            </>
          )}
          {step === 3 && (
            <>
              <button onClick={() => setStep(2)} className={BTN_GHOST} disabled={saving}>← Back</button>
              <button
                onClick={handleSave}
                disabled={saving || savableCount === 0}
                className={`${BTN_PRIMARY} flex-1`}
              >
                {saving ? (
                  <><RefreshCw className="w-4 h-4 animate-spin" /> Saving…</>
                ) : (
                  <><Save className="w-4 h-4" /> Confirm &amp; Save {savableCount} {savableCount === 1 ? cfg.masterSingular : cfg.masterPlural}</>
                )}
              </button>
            </>
          )}
          {step === 4 && (
            <button onClick={onClose} className={`${BTN_PRIMARY} flex-1`}>Close</button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Steps ────────────────────────────────────────────────────────────────────

function StepBar({ step }: { step: Step }) {
  return (
    <div className="flex items-center gap-0">
      {STEP_LABELS.map((label, i) => {
        const n = i + 1;
        const done = n < step;
        const active = n === step;
        return (
          <div key={label} className="flex items-center">
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                active ? "bg-[#1e3a5f] text-white" : done ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-400"
              }`}
            >
              <div
                className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                  active ? "bg-white text-[#1e3a5f]" : done ? "bg-green-500 text-white" : "bg-gray-300 text-gray-500"
                }`}
              >
                {done ? <Check className="w-3 h-3" /> : n}
              </div>
              {label}
            </div>
            {i < STEP_LABELS.length - 1 && <ChevronRight className="w-4 h-4 text-gray-300 mx-0.5" />}
          </div>
        );
      })}
    </div>
  );
}

function MappingStep({
  fields, sheet, mapping, onChange,
}: {
  fields: ImportField[];
  sheet: ParsedSheet;
  mapping: Record<string, string>;
  onChange: (key: string, col: string) => void;
}) {
  const matched = fields.filter((f) => mapping[f.key]).length;
  const unusedColumns = sheet.columns.filter((c) => !Object.values(mapping).includes(c));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-[11px] text-blue-700 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
        <Info className="w-3.5 h-3.5 shrink-0" />
        <span>
          {matched} of {fields.length} fields matched automatically. Check them, fix any that are wrong, and
          leave anything your file does not have unmapped.
        </span>
      </div>

      <div>
        <div className="grid grid-cols-2 gap-3 px-3 mb-1">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Our Field</p>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Your Column</p>
        </div>
        <div className="space-y-1">
          {fields.map((field) => (
            <div
              key={field.key}
              className="grid grid-cols-2 gap-3 items-center bg-gray-50/40 rounded-lg px-3 py-1.5 border border-gray-100 hover:border-blue-200 transition-colors"
            >
              <div>
                <span className="text-xs font-medium text-gray-700">
                  {field.label}
                  {field.required && <span className="text-red-500"> *</span>}
                </span>
                {field.hint && <p className="text-[10px] text-gray-400 mt-0.5">{field.hint}</p>}
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={mapping[field.key] ?? ""}
                  onChange={(e) => onChange(field.key, e.target.value)}
                  className={`flex-1 border rounded-md px-2.5 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                    field.required && !mapping[field.key] ? "border-red-300" : "border-gray-200"
                  }`}
                >
                  <option value="">— not in my file —</option>
                  {sheet.columns.map((col) => (
                    <option key={col} value={col}>{col}</option>
                  ))}
                </select>
                {mapping[field.key] ? (
                  <Check className="w-3.5 h-3.5 text-green-500 shrink-0" />
                ) : (
                  <span className="w-3.5 h-3.5 shrink-0" />
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {unusedColumns.length > 0 && (
        <p className="text-[11px] text-gray-400">
          Not imported: {unusedColumns.join(", ")}
        </p>
      )}

      <div>
        <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Your file (first 3 rows)
        </p>
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="w-full min-w-max">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                {sheet.columns.map((c) => (
                  <th key={c} className="px-2.5 py-1.5 text-left text-[10px] font-semibold text-white whitespace-nowrap">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sheet.rows.slice(0, 3).map((row, i) => (
                <tr key={i} className={i % 2 === 0 ? "bg-white" : "bg-gray-50/40"}>
                  {sheet.columns.map((c) => (
                    <td key={c} className="px-2.5 py-1.5 text-[11px] text-gray-700 max-w-32 truncate">
                      {row[c] || "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ReviewStep({
  fields, rows, rowErrors, onEdit, onToggle, savableCount, badCount, excludedCount, kind,
}: {
  fields: ImportField[];
  rows: ReviewRow[];
  rowErrors: Record<string, string>[];
  onEdit: (rowIdx: number, key: string, value: string) => void;
  onToggle: (rowIdx: number) => void;
  savableCount: number;
  badCount: number;
  excludedCount: number;
  kind: PartyKind;
}) {
  // Rows that name a company and leave at least one term blank. The server fills those
  // from the matching corporate on save — invisible in this grid, so say it here.
  const inheritCount = kind !== "customer" ? 0 : rows.filter((r, i) =>
    r.included
    && Object.keys(rowErrors[i]).length === 0
    && (r.values.company ?? "").trim()
    && INHERITED_FIELDS.some((k) => isBlankInherited(k, r.values[k] ?? ""))
  ).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold text-green-700 bg-green-50 border border-green-200 rounded-lg px-2.5 py-1.5">
          {savableCount} ready to save
        </span>
        {badCount > 0 && (
          <span className="text-[11px] font-semibold text-red-600 bg-red-50 border border-red-200 rounded-lg px-2.5 py-1.5 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" /> {badCount} need fixing — edit the cell or untick the row
          </span>
        )}
        {excludedCount > 0 && (
          <span className="text-[11px] font-semibold text-gray-500 bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5">
            {excludedCount} excluded
          </span>
        )}
        {inheritCount > 0 && (
          <span className="text-[11px] font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg px-2.5 py-1.5 flex items-center gap-1.5">
            <Info className="w-3.5 h-3.5 shrink-0" />
            {inheritCount} {inheritCount === 1 ? "row leaves" : "rows leave"} terms blank — where the
            company matches a corporate, those blanks are filled in from it on save. What you type here is kept.
          </span>
        )}
      </div>

      <div className="overflow-auto border border-gray-200 rounded-lg max-h-[46vh]">
        <table className="w-full min-w-max">
          <thead className="sticky top-0 z-10">
            <tr style={{ background: "#1e3a5f" }}>
              <th className="px-2 py-1.5 text-left text-[10px] font-semibold text-white">USE</th>
              <th className="px-2 py-1.5 text-left text-[10px] font-semibold text-white">ROW</th>
              {fields.map((f) => (
                <th key={f.key} className="px-2 py-1.5 text-left text-[10px] font-semibold text-white whitespace-nowrap">
                  {f.label.toUpperCase()}
                  {f.required && <span className="text-red-300"> *</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const errors = rowErrors[i];
              const hasError = row.included && Object.keys(errors).length > 0;
              return (
                <tr
                  key={i}
                  className={
                    !row.included ? "bg-gray-100/70 opacity-50"
                    : hasError ? "bg-red-50/50"
                    : i % 2 === 0 ? "bg-white" : "bg-gray-50/40"
                  }
                >
                  <td className="px-2 py-1">
                    <input
                      type="checkbox"
                      checked={row.included}
                      onChange={() => onToggle(i)}
                      className="w-3.5 h-3.5 accent-[#1e3a5f]"
                    />
                  </td>
                  <td className="px-2 py-1 text-[11px] text-gray-400 tabular-nums">{row.sheetRow}</td>
                  {fields.map((f) => (
                    <td key={f.key} className="px-1 py-1">
                      <Cell
                        field={f}
                        value={row.values[f.key] ?? ""}
                        error={row.included ? errors[f.key] : undefined}
                        disabled={!row.included}
                        onChange={(v) => onEdit(i, f.key, v)}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-gray-400">
        Only ticked rows without errors are saved. The server checks every one of them again.
      </p>
    </div>
  );
}

function Cell({
  field, value, error, disabled, onChange,
}: {
  field: ImportField;
  value: string;
  error?: string;
  disabled: boolean;
  onChange: (v: string) => void;
}) {
  const cls = `w-full border rounded px-1.5 py-1 text-[11px] bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:bg-transparent ${
    error ? "border-red-400 bg-red-50" : "border-gray-200"
  }`;

  if (field.type === "boolean") {
    return (
      <select value={value || "false"} onChange={(e) => onChange(e.target.value)} disabled={disabled} className={`${cls} min-w-28`} title={error}>
        <option value="false">Unregistered</option>
        <option value="true">Registered</option>
      </select>
    );
  }
  if (field.type === "choice") {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className={`${cls} min-w-32`} title={error}>
        <option value="">—</option>
        {(field.options ?? []).map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    );
  }
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      title={error}
      className={`${cls} min-w-28`}
    />
  );
}
