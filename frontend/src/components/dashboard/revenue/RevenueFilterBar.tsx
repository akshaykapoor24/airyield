"use client";

import { Filter, RotateCcw } from "lucide-react";
import MultiSelectDropdown from "@/components/ui/MultiSelectDropdown";
import {
  SOURCE_SHORT, type RevenueBasis, type RevenueFilterOptions, type RevenueScope,
} from "@/lib/revenueBoard";

export interface RevenueFilters {
  date_from: string;
  date_to: string;
  basis: RevenueBasis;
  scope: RevenueScope;
  currency: string;
  airline: number[];
  supplier: number[];
  source: string[];
  category: string[];
}

const SELECT =
  "py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none " +
  "focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white";

/**
 * ONE filter row, above everything it scopes.
 *
 * The same rule the accrual board's FilterBar states and for the same reason: every
 * tile, chart and matrix row below re-renders against this one slice, so a reader is
 * never comparing two differently-filtered pictures. Never a filter inside a chart card.
 *
 * The currency selector appears only when the board holds more than one. Totals are per
 * currency and are never converted or added across them, so with a single currency the
 * control would be a choice with one option and a rule nobody needs explaining.
 */
export default function RevenueFilterBar({
  value,
  onChange,
  options,
  extra,
}: {
  value: RevenueFilters;
  onChange: (next: RevenueFilters) => void;
  options?: RevenueFilterOptions;
  extra?: React.ReactNode;
}) {
  const set = (patch: Partial<RevenueFilters>) => onChange({ ...value, ...patch });
  const dirty =
    value.airline.length || value.supplier.length ||
    value.source.length || value.category.length;

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-3 flex flex-wrap items-start gap-2">
      <Filter className="w-4 h-4 text-gray-400 shrink-0 mt-2.5" aria-hidden />

      <input
        type="date"
        className={`${SELECT} h-9.5`}
        value={value.date_from}
        max={value.date_to || undefined}
        onChange={(e) => set({ date_from: e.target.value })}
        aria-label="From date"
      />
      <span className="text-xs text-gray-400 mt-3">to</span>
      <input
        type="date"
        className={`${SELECT} h-9.5`}
        value={value.date_to}
        min={value.date_from || undefined}
        onChange={(e) => set({ date_to: e.target.value })}
        aria-label="To date"
      />

      <select
        className={`${SELECT} h-9.5`}
        value={value.basis}
        onChange={(e) => set({ basis: e.target.value as RevenueBasis })}
        aria-label="Revenue basis"
        title="Which date a month is counted on. The same month holds different money under each."
      >
        <option value="issue">Sales basis</option>
        <option value="travel">Travel basis</option>
      </select>

      {options?.can_view_agency && (
        <select
          className={`${SELECT} h-9.5`}
          value={value.scope}
          onChange={(e) => set({ scope: e.target.value as RevenueScope })}
          aria-label="Scope"
        >
          <option value="agency">Whole agency</option>
          <option value="mine">My uploads</option>
        </select>
      )}

      {/* Only when there is a choice to make. */}
      {(options?.currencies.length ?? 0) > 1 && (
        <select
          className={`${SELECT} h-9.5`}
          value={value.currency}
          onChange={(e) => set({ currency: e.target.value })}
          aria-label="Currency"
          title="Totals are per currency and are never converted or added across them."
        >
          {options!.currencies.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      )}

      <div className="w-44">
        <MultiSelectDropdown
          placeholder="Airline"
          options={(options?.airlines ?? []).map((a) => ({
            value: a.id ?? -1, label: a.name,
          }))}
          selected={value.airline}
          onChange={(v) => set({ airline: v as number[] })}
        />
      </div>

      <div className="w-44">
        <MultiSelectDropdown
          placeholder="Consolidator"
          options={(options?.suppliers ?? []).map((s) => ({
            value: s.id ?? -1, label: s.name, sublabel: s.code ?? undefined,
          }))}
          selected={value.supplier}
          onChange={(v) => set({ supplier: v as number[] })}
        />
      </div>

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
          onClick={() =>
            onChange({ ...value, airline: [], supplier: [], source: [], category: [] })
          }
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 px-2 h-9.5 rounded-lg hover:bg-gray-100"
        >
          <RotateCcw className="w-3.5 h-3.5" aria-hidden /> Clear
        </button>
      )}

      <div className="ml-auto flex items-center gap-2">{extra}</div>
    </div>
  );
}
