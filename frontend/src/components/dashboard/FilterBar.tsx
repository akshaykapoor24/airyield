"use client";

import { Filter, RotateCcw } from "lucide-react";
import MultiSelectDropdown from "@/components/ui/MultiSelectDropdown";
import { STATUS, type AccrualFilterOptions, type StatusCode } from "@/lib/accrual";

export interface FilterState {
  period: string;
  basis: string;
  airline: string[];
  entity: string[];
  channel: string[];
  lob: string[];
  status: StatusCode[];
  search: string;
}

export const EMPTY_FILTERS: Omit<FilterState, "period" | "basis"> = {
  airline: [], entity: [], channel: [], lob: [], status: [], search: "",
};

/**
 * Seed the filter state from the query string once, on mount.
 *
 * Read off `window.location` rather than `useSearchParams` on purpose: the hook
 * opts the route out of static prerendering unless it is wrapped in Suspense,
 * and these pages are client-rendered anyway. Guarded for the server pass, where
 * `window` does not exist.
 *
 * This is what makes the Overview's exception cards work — each links to
 * `/dashboard/accrual?status=NO_RATE`, and the board must open already filtered.
 */
export function filtersFromUrl(): FilterState {
  const base: FilterState = { period: "", basis: "auto", ...EMPTY_FILTERS };
  if (typeof window === "undefined") return base;
  const p = new URLSearchParams(window.location.search);
  return {
    ...base,
    period: p.get("period") ?? "",
    basis: p.get("basis") ?? "auto",
    airline: p.getAll("airline"),
    entity: p.getAll("entity"),
    channel: p.getAll("channel"),
    lob: p.getAll("lob"),
    status: p.getAll("status") as StatusCode[],
    search: p.get("search") ?? "",
  };
}

const SELECT =
  "py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white";

const opts = (xs: string[]) => xs.map((x) => ({ value: x, label: x }));

/**
 * ONE filter row, above everything it scopes. Never a filter inside a chart card:
 * every tile, chart and grid row on the page re-renders against this same slice,
 * so a reader is never comparing two differently-filtered pictures.
 */
export default function FilterBar({
  value,
  onChange,
  options,
  showRowFilters = true,
  extra,
}: {
  value: FilterState;
  onChange: (next: FilterState) => void;
  options?: AccrualFilterOptions;
  showRowFilters?: boolean;
  extra?: React.ReactNode;
}) {
  const set = (patch: Partial<FilterState>) => onChange({ ...value, ...patch });
  const dirty =
    value.airline.length || value.entity.length || value.channel.length ||
    value.lob.length || value.status.length || value.search;

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-3 flex flex-wrap items-start gap-2">
      <Filter className="w-4 h-4 text-gray-400 shrink-0 mt-2.5" aria-hidden />

      <select
        className={`${SELECT} h-9.5`}
        value={value.period}
        onChange={(e) => set({ period: e.target.value })}
        aria-label="Period"
      >
        {(options?.periods ?? [{ key: value.period, label: value.period }]).map((p) => (
          <option key={p.key} value={p.key}>{p.label}</option>
        ))}
      </select>

      <select
        className={`${SELECT} h-9.5`}
        value={value.basis}
        onChange={(e) => set({ basis: e.target.value })}
        aria-label="Revenue basis"
        title="Which date a month is counted on. Auto follows each deal's own trigger type."
      >
        <option value="auto">Basis: auto</option>
        <option value="travel">Basis: flown date</option>
        <option value="issue">Basis: issue date</option>
      </select>

      {showRowFilters && (
        <>
          <div className="w-44">
            <MultiSelectDropdown
              placeholder="Airline"
              options={opts(options?.airlines ?? [])}
              selected={value.airline}
              onChange={(v) => set({ airline: v })}
            />
          </div>
          <div className="w-32">
            <MultiSelectDropdown
              placeholder="Entity"
              searchable={false}
              options={opts(options?.entities ?? [])}
              selected={value.entity}
              onChange={(v) => set({ entity: v })}
            />
          </div>
          <div className="w-32">
            <MultiSelectDropdown
              placeholder="Channel"
              searchable={false}
              options={opts(options?.channels ?? [])}
              selected={value.channel}
              onChange={(v) => set({ channel: v })}
            />
          </div>
          {!!options?.lobs.length && (
            <div className="w-36">
              <MultiSelectDropdown
                placeholder="LOB"
                searchable={false}
                options={opts(options.lobs)}
                selected={value.lob}
                onChange={(v) => set({ lob: v })}
              />
            </div>
          )}
          <div className="w-48">
            <MultiSelectDropdown
              placeholder="Status"
              searchable={false}
              options={(options?.statuses ?? []).map((s) => ({
                value: s, label: STATUS[s].label,
              }))}
              selected={value.status}
              onChange={(v) => set({ status: v as StatusCode[] })}
            />
          </div>
          <input
            className={`${SELECT} w-44 h-9.5`}
            placeholder="Search airline, entity…"
            value={value.search}
            onChange={(e) => set({ search: e.target.value })}
            aria-label="Search"
          />
        </>
      )}

      {!!dirty && (
        <button
          type="button"
          onClick={() => onChange({ ...value, ...EMPTY_FILTERS })}
          className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 px-2 h-9.5 rounded-lg hover:bg-gray-100"
        >
          <RotateCcw className="w-3.5 h-3.5" aria-hidden /> Clear
        </button>
      )}

      <div className="ml-auto flex items-center gap-2">{extra}</div>
    </div>
  );
}
