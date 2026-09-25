"use client";

import { Filter, RotateCcw } from "lucide-react";
import MultiSelectDropdown from "@/components/ui/MultiSelectDropdown";
import {
  SOURCE_SHORT, type RevenueFilterOptions, type RevenueScope,
} from "@/lib/revenueBoard";
import type { BoardQuery } from "@/lib/salesFlown";

/** The filter state of the Sales vs Flown and Risk analysis boards. */
export interface BoardFilters {
  date_from: string;
  date_to: string;
  as_of: string;
  scope: RevenueScope;
  currency: string;
  airline: number[];
  segment: "" | "D" | "I";
  source: string[];
}

export function toBoardQuery(f: BoardFilters): BoardQuery {
  return {
    scope: f.scope,
    date_from: f.date_from || undefined,
    date_to: f.date_to || undefined,
    as_of: f.as_of || undefined,
    airline: f.airline.length ? f.airline : undefined,
    segment: f.segment || undefined,
    source: f.source.length ? f.source : undefined,
    currency: f.currency || undefined,
  };
}

const SELECT =
  "py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none " +
  "focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white";

/**
 * One filter row above everything it scopes — the rule RevenueFilterBar and the accrual
 * FilterBar both keep. Options come off the Total Revenue board's /filters, so the
 * airline and statement-type pickers offer exactly what that board holds.
 *
 * The window is always the SALE window (issue date). "Flown as of" is the cut-off that
 * splits a sale into flown and not-yet-flown; it defaults to today.
 */
export default function BoardFilterBar({
  value,
  onChange,
  options,
  extra,
}: {
  value: BoardFilters;
  onChange: (next: BoardFilters) => void;
  options?: RevenueFilterOptions;
  extra?: React.ReactNode;
}) {
  const set = (patch: Partial<BoardFilters>) => onChange({ ...value, ...patch });
  const dirty = value.airline.length || value.source.length || value.segment;

  return (
    <div className="bg-white rounded-2xl ring-1 ring-line shadow-sm p-3 flex flex-wrap items-start gap-2">
      <Filter className="w-4 h-4 text-gray-400 shrink-0 mt-2.5" aria-hidden />

      <span className="text-[11px] text-gray-500 mt-3">Sold</span>
      <input
        type="date"
        className={`${SELECT} h-9.5`}
        value={value.date_from}
        max={value.date_to || undefined}
        onChange={(e) => set({ date_from: e.target.value })}
        aria-label="Sold from"
      />
      <span className="text-xs text-gray-400 mt-3">to</span>
      <input
        type="date"
        className={`${SELECT} h-9.5`}
        value={value.date_to}
        min={value.date_from || undefined}
        onChange={(e) => set({ date_to: e.target.value })}
        aria-label="Sold to"
      />

      <span className="text-[11px] text-gray-500 mt-3 ml-1">Flown as of</span>
      <input
        type="date"
        className={`${SELECT} h-9.5`}
        value={value.as_of}
        onChange={(e) => set({ as_of: e.target.value })}
        aria-label="Flown as of"
        title="A sale whose travel date is on or before this day counts as flown."
      />

      {options?.can_view_agency && (
        <select
          className={`${SELECT} h-9.5`}
          value={value.scope}
          onChange={(e) => set({ scope: e.target.value as RevenueScope })}
          aria-label="Scope"
        >
          <option value="auto">Default scope</option>
          <option value="agency">Whole agency</option>
          <option value="mine">My uploads</option>
        </select>
      )}

      {(options?.currencies.length ?? 0) > 1 && (
        <select
          className={`${SELECT} h-9.5`}
          value={value.currency}
          onChange={(e) => set({ currency: e.target.value })}
          aria-label="Currency"
          title="Totals are per currency and are never converted or added across them."
        >
          <option value="">Main currency</option>
          {options!.currencies.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      )}

      <div className="w-44">
        <MultiSelectDropdown
          placeholder="Airline"
          options={(options?.airlines ?? [])
            .filter((a) => a.id != null)
            .map((a) => ({ value: a.id as number, label: a.name }))}
          selected={value.airline}
          onChange={(v) => set({ airline: v as number[] })}
        />
      </div>

      <select
        className={`${SELECT} h-9.5`}
        value={value.segment}
        onChange={(e) => set({ segment: e.target.value as BoardFilters["segment"] })}
        aria-label="Segment"
      >
        <option value="">Dom + Intl</option>
        <option value="D">Domestic</option>
        <option value="I">International</option>
      </select>

      <div className="w-40">
        <MultiSelectDropdown
          placeholder="Statement type"
          searchable={false}
          options={(options?.sources ?? []).map((s) => ({
            value: s, label: SOURCE_SHORT[s] ?? s,
          }))}
          selected={value.source}
          onChange={(v) => set({ source: v as string[] })}
        />
      </div>

      {!!dirty && (
        <button
          type="button"
          onClick={() => onChange({ ...value, airline: [], source: [], segment: "" })}
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 px-2 h-9.5 rounded-lg hover:bg-gray-100"
        >
          <RotateCcw className="w-3.5 h-3.5" aria-hidden /> Clear
        </button>
      )}

      <div className="ml-auto flex items-center gap-2">{extra}</div>
    </div>
  );
}
