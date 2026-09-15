"use client";

// Step 1 of Report download: the period, how rows are dated, and which source
// types to look in. Controlled by the page, because "Run again" on a past report
// writes these filters back in. Upload counts come from GET /report-download/sources;
// a type the user has never uploaded is shown but disabled, so the tree always has
// the shape of Vendors → Statements.

import { useMemo } from "react";
import { AlertCircle, RefreshCw, Search } from "lucide-react";
import {
  BASIS_LABELS, BSP_SCOPE_LABELS, buildTypeTree, filterProblem, formatCount, formatDay,
  sortSourceKeys, subSourceLabel,
  type BspScope, type DateBasis, type ReportTypeNode, type SourceCategory, type UploadFilters,
} from "@/lib/reportDownload";
import { cn } from "@/lib/utils";

export type SourcesStatus = "loading" | "loaded" | "error";
type CheckState = "all" | "some" | "none";

const LABEL = "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1";
const INPUT =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";
const CHECKBOX = "w-3.5 h-3.5 accent-[#1e3a5f] cursor-pointer disabled:cursor-not-allowed shrink-0";

/** A checkbox that can show "some ticked". `indeterminate` exists only as a DOM
 *  property, so it is set through the ref. Shared with UploadPicker's group
 *  headers. */
export function TriStateCheckbox({
  state, onChange, disabled, label, className = CHECKBOX,
}: {
  state: CheckState;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label: string;
  className?: string;
}) {
  return (
    <input
      type="checkbox"
      aria-label={label}
      checked={state === "all"}
      ref={(el) => { if (el) el.indeterminate = state === "some"; }}
      onChange={() => onChange(state !== "all")}
      disabled={disabled}
      className={className}
    />
  );
}

export function checkState(keys: readonly string[], ticked: ReadonlySet<string>): CheckState {
  const n = keys.filter((k) => ticked.has(k)).length;
  return n === 0 ? "none" : n === keys.length ? "all" : "some";
}

export default function ReportFilters({
  value, onChange, sources, sourcesStatus, onRetrySources, onFind, finding,
}: {
  value: UploadFilters;
  onChange: (next: UploadFilters) => void;
  sources: SourceCategory[] | null;
  sourcesStatus: SourcesStatus;
  onRetrySources: () => void;
  onFind: () => void;
  finding: boolean;
}) {
  const tree = useMemo(() => buildTypeTree(sources), [sources]);
  const counts = useMemo(
    () => new Map((sources ?? []).flatMap((cat) => cat.types.map((t) => [t.key, t] as const))),
    [sources],
  );

  const ticked = useMemo(() => new Set(value.types), [value.types]);
  const loaded = sourcesStatus === "loaded";
  const totalUploads = useMemo(
    () => Array.from(counts.values()).reduce((s, c) => s + c.uploads, 0),
    [counts],
  );
  const problem = filterProblem(value);

  const uploadsFor = (key: string) => counts.get(key)?.uploads ?? 0;
  // Until the counts are in, nothing is known to be empty, so nothing is disabled.
  // A ticked type stays enabled even with no uploads (e.g. prefilled by Run again),
  // otherwise it could never be unticked.
  const keyDisabled = (key: string) => loaded && uploadsFor(key) === 0 && !ticked.has(key);

  // A group checkbox acts on the keys that can change. Counting a disabled key would
  // leave the group stuck at "some": ticking could never make it "all".
  const liveKeys = (keys: readonly string[]) => keys.filter((k) => !keyDisabled(k));

  const setKeys = (keys: readonly string[], on: boolean) => {
    const next = new Set(ticked);
    for (const k of keys) {
      if (on) next.add(k); else next.delete(k);
    }
    onChange({ ...value, types: sortSourceKeys(next) });
  };

  const countText = (keys: readonly string[]) => {
    if (sourcesStatus === "loading") return "…";
    if (!loaded) return "—";
    const n = keys.reduce((s, k) => s + uploadsFor(k), 0);
    return `${formatCount(n)} ${n === 1 ? "file" : "files"}`;
  };
  const rowsTitle = (keys: readonly string[]) => {
    if (!loaded) return undefined;
    const rows = keys.reduce((s, k) => s + (counts.get(k)?.rows ?? 0), 0);
    return `${formatCount(rows)} rows uploaded`;
  };

  const renderType = (node: ReportTypeNode) => {
    const live = liveKeys(node.keys);
    const allDisabled = live.length === 0;
    return (
      <li key={node.id} className="py-1">
        <label className={`flex items-center gap-2 text-xs ${allDisabled ? "text-gray-400" : "text-gray-700 cursor-pointer"}`}>
          <TriStateCheckbox state={checkState(live, ticked)} disabled={allDisabled} label={node.label}
            onChange={(on) => setKeys(live, on)} />
          <span className="flex-1 min-w-0 truncate">{node.label}</span>
          <span className="text-[11px] text-gray-400 tabular-nums" title={rowsTitle(node.keys)}>{countText(node.keys)}</span>
        </label>
        {node.keys.length > 1 && (
          <div className="ml-5 mt-1 flex flex-wrap gap-x-3 gap-y-1">
            {node.keys.map((key) => {
              const label = subSourceLabel(key, counts.get(key)?.label ?? key);
              const disabled = keyDisabled(key);
              return (
                <label key={key} title={rowsTitle([key])}
                  className={`flex items-center gap-1.5 text-[11px] ${disabled ? "text-gray-400" : "text-gray-600 cursor-pointer"}`}>
                  <input type="checkbox" checked={ticked.has(key)} disabled={disabled}
                    onChange={(e) => setKeys([key], e.target.checked)} className={CHECKBOX} />
                  {label}
                  {loaded && <span className="text-gray-400 tabular-nums">({formatCount(uploadsFor(key))})</span>}
                </label>
              );
            })}
          </div>
        )}
      </li>
    );
  };

  return (
    <section className="bg-white rounded-xl border border-gray-200">
      <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">Period and sources</p>
      </div>

      <div className="p-5 grid gap-6 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        {/* ── period, basis, BSP scope ── */}
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="rd-from" className={LABEL}>From</label>
              <input id="rd-from" type="date" value={value.date_from} max={value.date_to || undefined}
                onChange={(e) => onChange({ ...value, date_from: e.target.value })} className={INPUT} />
            </div>
            <div>
              <label htmlFor="rd-to" className={LABEL}>To</label>
              <input id="rd-to" type="date" value={value.date_to} min={value.date_from || undefined}
                onChange={(e) => onChange({ ...value, date_to: e.target.value })} className={INPUT} />
            </div>
          </div>

          <div>
            <span className={LABEL}>Date basis</span>
            <div role="radiogroup" aria-label="Date basis" className="grid grid-cols-2 rounded-lg border border-gray-200 p-0.5 bg-gray-50">
              {(Object.keys(BASIS_LABELS) as DateBasis[]).map((b) => {
                const active = value.basis === b;
                return (
                  <button key={b} type="button" role="radio" aria-checked={active}
                    onClick={() => onChange({ ...value, basis: b })}
                    className={`px-2 py-1.5 rounded-md text-[11px] font-medium transition-colors ${
                      active ? "bg-[#1e3a5f] text-white shadow-sm" : "text-gray-600 hover:bg-white"
                    }`}>
                    {BASIS_LABELS[b]}
                  </button>
                );
              })}
            </div>
            <p className="text-[10px] text-gray-400 mt-1">
              {value.basis === "transaction"
                ? "Rows dated in the period by their own issue or transaction date."
                : "Whole uploads that were uploaded in the period."}
            </p>
          </div>

          <fieldset disabled={value.basis === "upload"} className="disabled:opacity-50">
            <legend className={LABEL}>BSP scope</legend>
            <div className="space-y-1.5">
              {(Object.keys(BSP_SCOPE_LABELS) as BspScope[]).map((s) => (
                <label key={s} className="flex items-start gap-2 text-xs text-gray-700 cursor-pointer">
                  <input type="radio" name="rd-bsp-scope" value={s} checked={value.bsp_scope === s}
                    onChange={() => onChange({ ...value, bsp_scope: s })}
                    className="mt-0.5 w-3.5 h-3.5 accent-[#1e3a5f] cursor-pointer" />
                  <span>
                    {BSP_SCOPE_LABELS[s]}
                    {s === "whole_statement" && (
                      <span className="block text-[10px] text-gray-400">Needed to tie out to the statement&apos;s printed totals.</span>
                    )}
                  </span>
                </label>
              ))}
            </div>
            {value.basis === "upload" && (
              <p className="text-[10px] text-gray-400 mt-1">Applies to the issue / transaction date basis only.</p>
            )}
          </fieldset>
        </div>

        {/* ── category → type tree ── */}
        <div className="min-w-0">
          <div className="flex items-center justify-between gap-2 mb-2">
            <span className={cn(LABEL, "mb-0")}>Source types</span>
            {sourcesStatus === "loading" && (
              <span className="flex items-center gap-1 text-[11px] text-gray-400">
                <RefreshCw className="w-3 h-3 animate-spin" /> Counting uploads…
              </span>
            )}
            {sourcesStatus === "error" && (
              <span className="flex items-center gap-1.5 text-[11px] text-red-600">
                <AlertCircle className="w-3.5 h-3.5" /> Upload counts could not be loaded.
                <button type="button" onClick={onRetrySources} className="font-semibold underline hover:text-red-800">Retry</button>
              </span>
            )}
          </div>

          {loaded && totalUploads === 0 && (
            <p className="mb-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500">
              You have no uploads under Vendors → Statements yet. Upload a statement there first.
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {tree.map((cat) => {
              const keys = cat.types.flatMap((t) => t.keys);
              const live = liveKeys(keys);
              const disabled = live.length === 0;
              return (
                <div key={cat.category} className="rounded-lg border border-gray-200">
                  <label className={`flex items-center gap-2 px-3 py-2 border-b border-gray-100 bg-gray-50/60 rounded-t-lg ${
                    disabled ? "text-gray-400" : "text-gray-800 cursor-pointer"
                  }`}>
                    <TriStateCheckbox state={checkState(live, ticked)} disabled={disabled}
                      label={`All ${cat.category} sources`} onChange={(on) => setKeys(live, on)} />
                    <span className="flex-1 text-xs font-semibold">{cat.category}</span>
                    <span className="text-[11px] text-gray-400 tabular-nums">{countText(keys)}</span>
                  </label>
                  <ul className="px-3 py-1.5 divide-y divide-gray-50">{cat.types.map(renderType)}</ul>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="px-5 py-3 border-t border-gray-100 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className={`text-xs ${problem ? "text-amber-700" : "text-gray-500"}`}>
          {problem ?? `${value.types.length} source ${value.types.length === 1 ? "type" : "types"} · ${formatDay(value.date_from)} – ${formatDay(value.date_to)}`}
        </p>
        <button type="button" onClick={onFind} disabled={!!problem || finding}
          className="flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold text-white bg-[#1e3a5f] hover:bg-[#16304f] disabled:opacity-50 disabled:cursor-not-allowed">
          {finding ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
          {finding ? "Finding uploads…" : "Find uploads"}
        </button>
      </div>
    </section>
  );
}
