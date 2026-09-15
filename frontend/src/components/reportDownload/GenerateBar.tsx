"use client";

// Step 3 of Report download: what goes into the workbook and the button that
// queues it. Generation runs in the background (a Celery job), so this only
// submits; the report then appears in the history below with its progress. The
// server re-checks everything, and its refusals (409 too many reports running,
// 422 selection or size, 429 queue full) are shown here verbatim.

import { AlertCircle, FileDown, RefreshCw } from "lucide-react";
import { formatCount, type ReportOptions } from "@/lib/reportDownload";

const CHECKBOX = "mt-0.5 w-3.5 h-3.5 accent-[#1e3a5f] cursor-pointer shrink-0";

function Toggle({
  checked, onChange, label, help,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  help: string;
}) {
  return (
    <label className="flex items-start gap-2 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className={CHECKBOX} />
      <span className="min-w-0">
        <span className="block text-xs font-medium text-gray-700">{label}</span>
        <span className="block text-[10px] text-gray-400 leading-snug">{help}</span>
      </span>
    </label>
  );
}

export default function GenerateBar({
  fileCount, estimatedRows, options, onOptionsChange, showUndatedOption,
  title, onTitleChange, onGenerate, submitting, blockedReason, error,
}: {
  fileCount: number;
  estimatedRows: number;
  options: ReportOptions;
  onOptionsChange: (next: ReportOptions) => void;
  /** Only offered when a ticked upload actually has undated rows. */
  showUndatedOption: boolean;
  title: string;
  onTitleChange: (title: string) => void;
  onGenerate: () => void;
  submitting: boolean;
  blockedReason: string | null;
  error: string | null;
}) {
  return (
    <section className="bg-white rounded-xl border border-gray-200">
      <div className="p-5 flex flex-col gap-5 lg:flex-row lg:items-start">
        <div className="lg:w-56 shrink-0">
          <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Report</p>
          <p className="text-lg font-bold text-gray-900 mt-0.5 tabular-nums">
            {formatCount(fileCount)} {fileCount === 1 ? "file" : "files"}
            <span className="text-gray-400 font-medium"> · ~{formatCount(estimatedRows)} rows</span>
          </p>
          <p className="text-[10px] text-gray-400 mt-0.5">An upper estimate of rows on the Combined sheet.</p>
        </div>

        <div className="flex-1 grid gap-3 sm:grid-cols-2">
          <Toggle
            checked={options.include_detail_sheets}
            onChange={(v) => onOptionsChange({ ...options, include_detail_sheets: v })}
            label="Include detail sheets"
            help="One sheet per source with its native columns, joined to Combined by Row Ref."
          />
          <Toggle
            checked={options.include_pii}
            onChange={(v) => onOptionsChange({ ...options, include_pii: v })}
            label="Include passenger contact details"
            help="PAN, passport, phone, email and address. Card data is never exported."
          />
          {showUndatedOption && (
            <Toggle
              checked={options.undated_rows === "include"}
              onChange={(v) => onOptionsChange({ ...options, undated_rows: v ? "include" : "exclude" })}
              label="Include rows without a readable date"
              help="Kept and flagged DATE_UNREADABLE, so nothing drops out silently."
            />
          )}
          <div className={showUndatedOption ? "" : "sm:col-span-2"}>
            <label htmlFor="rd-title" className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
              Title <span className="normal-case font-normal text-gray-400">(optional)</span>
            </label>
            <input id="rd-title" type="text" value={title} maxLength={200}
              onChange={(e) => onTitleChange(e.target.value)}
              placeholder="e.g. August 2026 vendor statements"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400" />
          </div>
        </div>

        <div className="lg:w-48 shrink-0 flex flex-col gap-1.5">
          <button type="button" onClick={onGenerate} disabled={submitting || !!blockedReason}
            className="flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg text-xs font-semibold text-white bg-[#1e3a5f] hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed">
            {submitting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
            {submitting ? "Queuing…" : "Generate report"}
          </button>
          {blockedReason && <p className="text-[11px] text-amber-700 leading-snug">{blockedReason}</p>}
        </div>
      </div>

      {error && (
        <div className="mx-5 mb-5 flex items-start gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700" role="alert">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /> {error}
        </div>
      )}
    </section>
  );
}
